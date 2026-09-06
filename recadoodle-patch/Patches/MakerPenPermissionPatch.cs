using System;
using HarmonyLib;

namespace Recadoodle.Patches;

internal static class MakerPenPermissionPatch
{
    private static readonly string[] GetterNames =
    {
        "get_CanUseMakerPen",
        "get_canUseMakerPen",
        "RecRoom_Systems_PlayerRoles_ICreatorRole_get_CreatorRoleCanUseMakerPen",
    };

    internal static void Apply(Harmony harmony)
    {
        var roleType = typeof(RecRoom.Systems.PlayerRoles.GameRole);
        var postfix = new HarmonyMethod(typeof(MakerPenPermissionPatch), nameof(Postfix));

        foreach (var getterName in GetterNames)
        {
            var getter = AccessTools.Method(roleType, getterName);
            if (getter == null || getter.ReturnType != typeof(bool))
            {
                Plugin.Log.LogWarning($"[MAKER-PEN] {roleType.FullName}.{getterName} is unavailable; skipping it.");
                continue;
            }

            harmony.Patch(getter, postfix: postfix);
            Plugin.Log.LogInfo($"[MAKER-PEN] Enabled override for {roleType.FullName}.{getterName}.");
        }
    }

    private static void Postfix(ref bool __result)
    {
        if (Plugin.AllowMakerPenInQuests.Value)
            __result = true;
    }
}
