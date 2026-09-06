using HarmonyLib;
using RecRoom.AntiCheat;
using System.Text;
using Il2CppSystem;

namespace Recadoodle.Patches;

[HarmonyPatch]
public static class EACPatches
{
    [HarmonyPrefix]
    // The "is ready" check: the only static, 0-param bool method on EACManager that isn't a property
    // getter. 20230414 build: MCFIOBHCFBB (was IMMGELPFGCK, was FJLMLEPOKGE). Method names here are
    // strings, so a rename is not a compile error — it shows up as a HarmonyX "method not found" at load.
    [HarmonyPatch(typeof(EACManager), "MCFIOBHCFBB")]
    private static bool IsReadyPatch(ref bool __result)
    {
        __result = true;
        return false;
    }

    [HarmonyPrefix]
    [HarmonyPatch(typeof(EACManager), "GenerateChallengeResponse")]
    // __0 = the challenge string (positional); obfuscated param names shift between game builds.
    private static bool GenerateChallengeResponsePatch(string __0, ref string __result)
    {
        if (!string.IsNullOrEmpty(__0))
            __result = Convert.ToBase64String(Encoding.UTF8.GetBytes(__0));
        else
            __result = Convert.ToBase64String(Encoding.UTF8.GetBytes("nothing"));
        return false;
    }
}