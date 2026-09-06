using HarmonyLib;

namespace Recadoodle.Patches;

/// <summary>
/// Enables only the RRUI watch feature switches already bundled in the April 2023
/// client. The original getters query Statsig, which is unavailable on a replacement
/// backend and otherwise causes the client to fall back to the legacy watch UI.
/// </summary>
internal static class NewWatchMenuPatch
{
    private static readonly string[] PropertyNames =
    {
        "UseNewWatchArchitecture",
        "UseRRUIHomeScreen",
        "UseRRUINotificationsScreen",
    };

    internal static void Apply(Harmony harmony)
    {
        var watchUi = typeof(RecRoom.Core.WatchUI);
        var postfix = new HarmonyMethod(typeof(NewWatchMenuPatch), nameof(Postfix));

        foreach (var propertyName in PropertyNames)
        {
            var getter = AccessTools.PropertyGetter(watchUi, propertyName);
            if (getter == null)
            {
                Plugin.Log.LogWarning(
                    $"[NEW-WATCH] {watchUi.FullName}.{propertyName} is not present in this build; skipping it.");
                continue;
            }

            harmony.Patch(getter, postfix: postfix);
            Plugin.Log.LogInfo($"[NEW-WATCH] Enabled {watchUi.FullName}.{propertyName}.");
        }
    }

    private static void Postfix(ref bool __result)
    {
        if (Plugin.EnableNewWatchMenu.Value)
            __result = true;
    }
}
