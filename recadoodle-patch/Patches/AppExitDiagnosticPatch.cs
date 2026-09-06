using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace Recadoodle.Patches;

/// <summary>
/// Records every managed entry point into the April 2023 client's application-exit
/// state machine. This deliberately does not suppress or alter shutdown behavior.
/// </summary>
[HarmonyPatch]
internal static class AppExitDiagnosticPatch
{
    private static IEnumerable<MethodBase> TargetMethods()
    {
        var lifecycle = typeof(FKPMPGLFHBE);

        // These are the two public, parameterless entry points on the obfuscated
        // application lifecycle controller. One handles the quit request and the
        // other advances/completes it; logging both lets us distinguish the caller.
        yield return AccessTools.Method(lifecycle, "IHEKMEOIBOI");
        yield return AccessTools.Method(lifecycle, "HIMGBACNCPJ");
    }

    private static void Prefix(MethodBase __originalMethod)
    {
        Plugin.Log.LogWarning(
            $"[APP-EXIT-DIAGNOSTIC] Entered {__originalMethod.DeclaringType?.FullName}." +
            $"{__originalMethod.Name}\n{Environment.StackTrace}");
    }
}

[HarmonyPatch]
internal static class AppExitStateDiagnosticPatch
{
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(FKPMPGLFHBE), "EIAPBOMKLCN");

    private static void Prefix(FKPMPGLFHBE.NMDDLMDPPCH __0)
    {
        Plugin.Log.LogWarning(
            $"[APP-EXIT-DIAGNOSTIC] State requested: {__0}\n{Environment.StackTrace}");
    }
}
