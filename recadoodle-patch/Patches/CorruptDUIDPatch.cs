using HarmonyLib;
using UnityEngine;

namespace Recadoodle.Patches;

// Test tool: persist a genuinely corrupt STORED device id on this machine, matching the friend's
// condition (stored id truncated, current id healthy).
//
// We can't hand-craft the stored value: it lives in PlayerPrefs under an obfuscated key, encoded as a
// CodeStage ObscuredString, and both the key and the encode method are renamed per game build. So we
// let the game write it: WriteDUIDs() stores ObscuredString(SystemInfo.deviceUniqueIdentifier) under
// the right key. We temporarily spoof deviceUniqueIdentifier to a truncated value around that one
// call, so the game encrypts+stores a bad id with its own (unknown-to-us) key. Afterwards the spoof
// is off, so the current id reads healthy again -> stored != current -> real mismatch on next launch.
[HarmonyPatch]
public static class CorruptDUIDPatch
{
    // Only true for the duration of the WriteDUIDs() call below, so the SystemInfo getter is spoofed
    // exactly there and nowhere else.
    private static bool _spoofActive;
    private static string _spoofValue = "";

    [HarmonyPrefix]
    [HarmonyPatch(typeof(SystemInfo), "get_deviceUniqueIdentifier")]
    private static bool DeviceIdGetterPrefix(ref string __result)
    {
        if (!_spoofActive)
            return true;
        __result = _spoofValue;
        return false;
    }

    // Returns true if the corruption was written (so the caller marks it done and won't repeat).
    public static bool CorruptStored(GameObject cheatMgrGo)
    {
        var cm = cheatMgrGo.GetComponent<CheatManager>() ?? cheatMgrGo.GetComponentInChildren<CheatManager>();
        if (cm == null)
        {
            Plugin.Log.LogError("[CORRUPT] could not find CheatManager component; nothing written");
            return false;
        }

        var real = SystemInfo.deviceUniqueIdentifier; // spoof off -> real id
        var bad = real is { Length: >= 7 } ? real.Substring(0, 7) : "badduid";

        _spoofValue = bad;
        _spoofActive = true;
        try
        {
            cm.WriteDUIDs(); // encodes+stores ObscuredString(bad) under the real key
        }
        finally
        {
            _spoofActive = false;
        }

        Plugin.Log.LogWarning($"[CORRUPT] wrote truncated stored DUID = \"{bad}\" (real id = \"{real}\"). " +
                              "Set 'Corrupt Stored DUID' back to false and relaunch to drive the real mismatch path.");
        return true;
    }

    // Undo: overwrite the stored value with the real id by calling WriteDUIDs with the spoof off.
    public static bool RestoreStored(GameObject cheatMgrGo)
    {
        var cm = cheatMgrGo.GetComponent<CheatManager>() ?? cheatMgrGo.GetComponentInChildren<CheatManager>();
        if (cm == null)
        {
            Plugin.Log.LogError("[CORRUPT] could not find CheatManager component; nothing restored");
            return false;
        }

        cm.WriteDUIDs(); // spoof off -> stores ObscuredString(real deviceUniqueIdentifier)
        Plugin.Log.LogWarning($"[CORRUPT] restored stored DUID to real id = \"{SystemInfo.deviceUniqueIdentifier}\". " +
                              "Set 'Restore Stored DUID' back to false.");
        return true;
    }
}
