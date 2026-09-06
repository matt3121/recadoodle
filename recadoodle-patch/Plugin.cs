using System;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Recadoodle;

[BepInPlugin("dev.recadoodle.patch", "Recadoodle", "1.0.0")]
public class Plugin : BasePlugin
{
    internal static new ManualLogSource Log;

    public static ConfigEntry<string> AppIdRT { get; private set; }
    public static ConfigEntry<string> AppIdVoice { get; private set; }
    public static ConfigEntry<string> AppIdChat { get; private set; }
    public static ConfigEntry<string> ServerHostname { get; private set; }
    public static ConfigEntry<bool> EnableAdvancedSettings { get; private set; }
    public static ConfigEntry<string> PhotonHostname { get; private set; }
    public static ConfigEntry<int> PhotonPort { get; private set; }
    public static ConfigEntry<bool> Debug { get; private set; }
    public static ConfigEntry<bool> SimulateDUIDMismatch { get; private set; }
    public static ConfigEntry<bool> SuppressDUIDMismatch { get; private set; }
    public static ConfigEntry<bool> CorruptStoredDUID { get; private set; }
    public static ConfigEntry<bool> RestoreStoredDUID { get; private set; }
    public static ConfigEntry<string> DeviceIdResponseOverride { get; private set; }
    public static ConfigEntry<int> DeviceIdResponseStatus { get; private set; }
    public static ConfigEntry<bool> DisableSignatureVerification { get; private set; }
    public static ConfigEntry<bool> DisableTelemetry { get; private set; }
    public static ConfigEntry<bool> EnableNewWatchMenu { get; private set; }
    public static ConfigEntry<bool> EnableDarkUI { get; private set; }
    public static ConfigEntry<bool> AllowMakerPenInQuests { get; private set; }
    public static ConfigEntry<bool> EnableAdminMenu { get; private set; }
    public static ConfigEntry<string> WatchAccentColor { get; private set; }
    public static ConfigEntry<string> WatchBackgroundColor { get; private set; }
    public static ConfigEntry<string> AdminMenuColor { get; private set; }

    private static bool _corruptDone;

    public override void Load()
    {
        Log = base.Log;

        AppIdRT = Config.Bind("Photon", "App Id Realtime", "", "Photon Realtime App ID");
        AppIdVoice = Config.Bind("Photon", "App Id Voice", "", "Photon Voice App ID");
        AppIdChat = Config.Bind("Photon", "App Id Chat", "", "Photon Chat App ID");
        EnableAdvancedSettings = Config.Bind("Advanced", "Enabled Advanced Settings", false, "Allows other fields below in the advanced section to be modified.");
        PhotonHostname = Config.Bind("Advanced", "Photon NameServer", "", "Custom Photon NameServer");
        PhotonPort = Config.Bind("Advanced", "Photon NameServer Port", 0, "Custom Photon NameServer Port (if 0, it will be default)");
        ServerHostname = Config.Bind("Server", "RecNet NameServer Host", "http://127.0.0.1:5000", "Host for the Recadoodle server.");
        Debug = Config.Bind("Advanced", "Debug", false, "Show debug logs (HTTP tracing, etc. WARNING: will include sensitive information such as passwords and auth tokens in the logs, be careful when sharing them!)");
        SimulateDUIDMismatch = Config.Bind("Advanced", "Simulate DUID Mismatch", false, "Force CheckForDUIDMismatch to return TRUE (fakes the comparison only). Reproduces the hang path but does not corrupt any stored value. Leave false for normal play.");
        SuppressDUIDMismatch = Config.Bind("Advanced", "Suppress DUID Mismatch", true, "Force CheckForDUIDMismatch to return FALSE (the workaround fix, ON by default): the client never migrates and never takes the Create Account hang path. No-op on healthy machines (the real check returns false anyway); on mismatched machines it skips the hang. Set false only to observe the real mismatch behavior for debugging.");
        CorruptStoredDUID = Config.Bind("Advanced", "Corrupt Stored DUID", false, "ONE-SHOT TEST: on next launch, write a truncated device id into the DUID pref via the game's own WriteDUIDs, producing a genuinely corrupt STORED value (real current id) — exactly the friend's condition. After it logs '[CORRUPT] wrote', set this back to false and relaunch to drive the real mismatch path. Use 'Restore Stored DUID' to undo.");
        RestoreStoredDUID = Config.Bind("Advanced", "Restore Stored DUID", false, "ONE-SHOT UNDO: on next launch, call WriteDUIDs with the real device id, overwriting any corrupt stored value with a good one. Set back to false after it logs '[CORRUPT] restored'.");
        DeviceIdResponseOverride = Config.Bind("Advanced", "DeviceId Response Override", "", "Replace the body of the PlayerReporting/v1/deviceId response with this text, to test what shape the client will accept. Empty = leave the server's response alone.");
        DeviceIdResponseStatus = Config.Bind("Advanced", "DeviceId Response Status", 200, "HTTP status to force on the PlayerReporting/v1/deviceId response. Only applies when the override body is set.");

        DisableSignatureVerification = Config.Bind("Signing", "Disable Signature Verification", true, "Force RSA signature verification to succeed (ON by default), so the client can load images served by Recadoodle. NOTE: this applies to all mscorlib RSA verification, not only image signatures.");

        DisableTelemetry = Config.Bind("Analytics", "Disable Telemetry", true, "Stop the client reporting to third-party telemetry services (ON by default). Covers Amplitude analytics, data-collection hosts, and Backtrace crash reports, minidumps, and metrics. Blocked uploads get a synthetic 200 so the client can continue. Unity performance events may still be sent by native engine code. Set false to allow telemetry.");

        EnableNewWatchMenu = Config.Bind(
            "Interface",
            "Enable New Watch Menu",
            true,
            "Enable the RRUI watch architecture, home screen, and notifications screen bundled with the April 2023 client.");
        EnableDarkUI = Config.Bind(
            "Interface",
            "Enable Dark UI",
            true,
            "Apply the selected dark theme to Watch, RRUI, login, and account-picker screens.");
        AllowMakerPenInQuests = Config.Bind(
            "Permissions",
            "Allow Maker Pen In Quests",
            true,
            "Treat gameplay roles as Maker Pen-enabled, including quest roles.");
        EnableAdminMenu = Config.Bind("Interface", "Enable Admin Menu", true, "Show the developer mod menu when F8 is pressed.");
        WatchAccentColor = Config.Bind("Interface", "Watch Accent Color", "Orange", "Watch accent preset: Orange, Blue, Purple, Green, Red, or Pink.");
        WatchBackgroundColor = Config.Bind("Interface", "Watch Background Color", "Charcoal", "Watch background preset: Charcoal, Navy, Slate, Purple, or Black.");
        AdminMenuColor = Config.Bind("Interface", "Admin Menu Color", "Blue", "F8 menu preset: Blue, Orange, Purple, Green, Red, or Gray.");

        // Not a patch — Unity's telemetry has a real opt-out, so we just set it. Retried from
        // OnSceneLoaded until it takes, since the native setters can refuse this early.
        Patches.UnityTelemetryPatch.Apply();

        var harmony = new Harmony("dev.recadoodle.patch");
        harmony.PatchAll(typeof(Plugin).Assembly);
        Patches.MakerPenPermissionPatch.Apply(harmony);
        ClassInjector.RegisterTypeInIl2Cpp<Patches.DarkUIController>();
        ClassInjector.RegisterTypeInIl2Cpp<Patches.AdminMenuController>();
        AddComponent<Patches.DarkUIController>();
        AddComponent<Patches.AdminMenuController>();
        // The April build reads its RRUI watch switches from
        // /api/gameconfigs/v1/all. Do not patch guessed WatchUI properties;
        // the config service is the authoritative switch for this build.

        // The April 2023 client uses a generated Utf8Json formatter for the
        // ConsumePageView response. Dump its encoded member names once so the
        // replacement backend can return the exact wire shape this build expects.
        try
        {
            var formatter = new DNHALLICNCL();
            for (var i = 0; i < formatter.DLPJHHIHOLN.Length; i++)
            {
                var encoded = formatter.DLPJHHIHOLN[i];
                var managed = new byte[encoded.Length];
                for (var j = 0; j < encoded.Length; j++)
                    managed[j] = encoded[j];
                Log.LogInfo($"[PAGEVIEW-SCHEMA] {i}: {System.Text.Encoding.UTF8.GetString(managed)}");
            }
        }
        catch (Exception e)
        {
            Log.LogWarning($"[PAGEVIEW-SCHEMA] Could not read formatter keys: {e}");
        }

        SceneManager.sceneLoaded += (Action<Scene, LoadSceneMode>)OnSceneLoaded;
    }

    private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
    {
        // No-op once the switches have stuck; must run before the early return below.
        Patches.UnityTelemetryPatch.Apply();

        // CheatManager boots us out of rooms when it runs, but it's ALSO the DUID service the DI
        // container resolves for account creation / login (destroying it removes that service).
        // So instead of destroying it, *deactivate* the GameObject: it stops running (no Update /
        // coroutines, so no boot) while the component still exists, so the DI container can still
        // resolve PGECJHKNIEN and call its DUID methods. It's recreated per scene, so deactivate
        // each freshly-spawned (active) instance on every load. (GameObject.Find only returns active
        // objects, so once deactivated it isn't found again.)
        var cheatMgr = GameObject.Find("GameRoot/(Startup)(Clone)/Core Systems/[CheatManager]");
        if (cheatMgr == null)
            return;

        // One-shot corruption for testing: must run while the component is still active (before we
        // deactivate it below), because it calls the live CheatManager.WriteDUIDs().
        if (CorruptStoredDUID.Value && !_corruptDone)
            _corruptDone = Patches.CorruptDUIDPatch.CorruptStored(cheatMgr);
        else if (RestoreStoredDUID.Value && !_corruptDone)
            _corruptDone = Patches.CorruptDUIDPatch.RestoreStored(cheatMgr);

        cheatMgr.SetActive(false);
        Log.LogInfo("cheatmanager deactivated");
    }
}
