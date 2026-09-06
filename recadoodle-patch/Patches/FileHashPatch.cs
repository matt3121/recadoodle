using HarmonyLib;

namespace Recadoodle.Patches;

/// <summary>
/// Disables the legacy client file-integrity checker. Its signed manifest was
/// hosted by the original service and is no longer available for this build;
/// a failed manifest download otherwise asks the application to exit when Play
/// is pressed.
/// </summary>
[HarmonyPatch(typeof(IJEHEPHLCII), "IHEKMEOIBOI")]
internal static class FileHashPatch
{
    [HarmonyPrefix]
    private static bool SkipFileHashCheck()
    {
        Plugin.Log.LogInfo("Legacy file-integrity check skipped");
        return false;
    }
}
