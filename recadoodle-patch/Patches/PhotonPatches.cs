using ExitGames.Client.Photon;
using HarmonyLib;
using Photon.Realtime;

namespace Recadoodle.Patches;

/**
    Patches Photon to use the App IDs and server hostname/port specified in the plugin config.
 */
// Obfuscated names shift every game build. Re-resolve by signature: the target is the only
// instance, 0-param method returning Photon.Realtime.AppSettings in Assembly-CSharp.
// 20230414 build: HPEENKELKDJ.MGKINLFMJLB (was LEALBOODIEE.GBNKOFMAJPA, was GPFPFDBGCEK.AMOHMPKKGHL).
[HarmonyPatch(typeof(HPEENKELKDJ), "MGKINLFMJLB")]
public class PhotonPatches
{
    [HarmonyPostfix]
    private static void Postfix(ref AppSettings __result)
    {
        if (__result != null)
        {
            __result.AppIdRealtime = Plugin.AppIdRT.Value;
            __result.AppIdVoice = Plugin.AppIdVoice.Value;
            __result.AppIdChat = Plugin.AppIdChat.Value;
            __result.FixedRegion = "us";
            __result.UseNameServer = true;
            __result.Protocol = ConnectionProtocol.Udp;

            if (Plugin.EnableAdvancedSettings.Value)
            {
                __result.Server = Plugin.PhotonHostname.Value;
                __result.Port = Plugin.PhotonPort.Value == 0
                    ? 4533
                    : Plugin.PhotonPort.Value;
            }
        }
    }
}
