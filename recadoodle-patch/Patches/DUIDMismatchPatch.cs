using HarmonyLib;

namespace Recadoodle.Patches;

// Controls CheatManager.CheckForDUIDMismatch, which returns true when the machine's stored device id
// differs from the freshly-derived one. A true result sends the client down the migration path that
// POSTs PlayerReporting/v1/deviceId and then stalls on Create Account.
//
// Three modes, chosen by config:
//   Simulate = true  -> force TRUE  (fake a mismatch to reproduce the hang without a corrupt value)
//   Suppress = true  -> force FALSE (the workaround fix: never migrate, never hang)
//   both false       -> pass through, let the REAL check run against the actual stored value
//                       (needed to observe a genuinely corrupt stored id, e.g. after Corrupt Stored DUID)
//
// Patch the concrete CheatManager method, NOT the abstract PGECJHKNIEN interface, or the prefix
// never runs.
[HarmonyPatch]
public static class DUIDMismatchPatch
{
    private const string SimulatedStoredDeviceId = "491e8b9";

    [HarmonyPrefix]
    [HarmonyPatch(typeof(CheatManager), "CheckForDUIDMismatch")]
    // __0 = the out-param (positional). Its obfuscated name changes every game build, so binding it
    // by name throws "Parameter ... not found" on upgrade.
    private static bool Prefix(ref string __0, ref bool __result)
    {
        if (Plugin.SimulateDUIDMismatch.Value)
        {
            __0 = SimulatedStoredDeviceId;
            __result = true;
            Plugin.Log.LogWarning($"[DUID] simulating mismatch, stored id = {SimulatedStoredDeviceId}");
            return false;
        }

        if (Plugin.SuppressDUIDMismatch.Value)
        {
            __0 = string.Empty;
            __result = false;
            Plugin.Log.LogInfo("[DUID] mismatch check forced to false (suppressed)");
            return false;
        }

        // Pass through to the real check.
        return true;
    }
}
