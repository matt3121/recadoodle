using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace Recadoodle.Patches;

// Diagnostic only. Two jobs:
//   1. Show where the stored device id lives, by logging PlayerPrefs reads/writes.
//   2. Show how far the DUID migration branch gets, by logging CheatManager's other DUID methods.
//      If WriteDUIDs() never fires after the deviceId POST, the flow stalls before it.
[HarmonyPatch]
public static class DUIDProbePatch
{
    // PlayerPrefs.GetString is called constantly, so log each key only once — except device/DUID
    // keys, which we always log so we can watch them change across the migration.
    private static readonly HashSet<string> SeenKeys = new();

    private static bool IsInteresting(string key) =>
        key != null && (key.Contains("DUID") || key.Contains("Duid") || key.Contains("duid")
                     || key.Contains("Device") || key.Contains("device")
                     || key.Contains("Anon") || key.Contains("anon"));

    private static void Note(string op, string key, string value)
    {
        if (IsInteresting(key))
            Plugin.Log.LogWarning($"[DUID-PROBE] {op} {key} = \"{value}\"");
        else if (SeenKeys.Add($"{op}:{key}"))
            Plugin.Log.LogInfo($"[DUID-PROBE] {op} {key} = \"{value}\"");
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(PlayerPrefs), nameof(PlayerPrefs.GetString), [typeof(string)])]
    private static void GetStringPostfix(string key, string __result) => Note("get", key, __result);

    [HarmonyPostfix]
    [HarmonyPatch(typeof(PlayerPrefs), nameof(PlayerPrefs.GetString), [typeof(string), typeof(string)])]
    private static void GetStringDefaultPostfix(string key, string __result) => Note("get", key, __result);

    [HarmonyPrefix]
    [HarmonyPatch(typeof(PlayerPrefs), nameof(PlayerPrefs.SetString))]
    private static void SetStringPrefix(string key, string value) => Note("SET", key, value);

    [HarmonyPrefix]
    [HarmonyPatch(typeof(PlayerPrefs), nameof(PlayerPrefs.DeleteKey))]
    private static void DeleteKeyPrefix(string key) => Note("DEL", key, "<deleted>");

    [HarmonyPrefix]
    [HarmonyPatch(typeof(CheatManager), "WriteDUIDs")]
    private static void WriteDUIDsPrefix() => Plugin.Log.LogWarning("[DUID-PROBE] WriteDUIDs() called");

    [HarmonyPostfix]
    [HarmonyPatch(typeof(CheatManager), "WriteDUIDs")]
    private static void WriteDUIDsPostfix() => Plugin.Log.LogWarning("[DUID-PROBE] WriteDUIDs() returned");

    [HarmonyPrefix]
    [HarmonyPatch(typeof(CheatManager), "ClearDUIDs")]
    private static void ClearDUIDsPrefix() => Plugin.Log.LogWarning("[DUID-PROBE] ClearDUIDs() called");
}
