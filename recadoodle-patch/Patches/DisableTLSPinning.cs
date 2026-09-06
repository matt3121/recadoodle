using HarmonyLib;
using Org.BouncyCastle.Crypto.Tls;

namespace Recadoodle.Patches;

/**
    Disables TLS certificate pinning. Even though we connect over SSL it seems some certificates
    might be pinned.
*/
public class DisableTLSPinning
{
    [HarmonyPatch(typeof(LegacyTlsAuthentication), "NotifyServerCertificate")]
    public class TlsPatch
    {
        private static bool Prefix()
        {
            return false;
        }
    }
}
