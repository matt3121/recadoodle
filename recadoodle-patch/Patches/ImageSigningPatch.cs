using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppSystem.Security.Cryptography;

namespace Recadoodle.Patches;

// Image signing: the client verifies images against an RSA public key whose modulus is a string
// literal in global-metadata.dat. Patching that literal is fragile, so we intervene at the framework
// level instead, by forcing the mscorlib RSA verify to succeed.
//
// One knob, see [Signing] in the .cfg:
//   Disable Signature Verification -> THE FIX (default true). Forces the RSA verify to succeed, so
//                                    the modulus never has to match and unsigned images load. This
//                                    self-hosted setup does not use image signing.
//
// If images ever stop loading with this on, the client has moved verification off mscorlib RSA onto
// BestHTTP.SecureProtocol.Org.BouncyCastle; the equivalent hooks there are the concrete
// RsaDigestSigner/PssSigner.VerifySignature (NOT the abstract ISigner "interface", which never
// dispatches).
[HarmonyPatch]
public static class ImageSigningPatch
{
    private static bool _loggedForced;

    // Forces EVERY mscorlib RSA verification to succeed, not just image signatures. BestHTTP's TLS
    // uses its own bundled BouncyCastle rather than mscorlib RSA, so this should not touch
    // certificate validation — but it is a blunt instrument, so it stays behind a config knob rather
    // than being unconditional.
    private static bool ForceVerifyTrue(ref bool __result)
    {
        if (!Plugin.DisableSignatureVerification.Value)
            return true;

        if (!_loggedForced)
        {
            _loggedForced = true;
            Plugin.Log.LogWarning("[SIG] signature verification disabled — RSA verify forced to true");
        }

        __result = true;
        return false;
    }

    [HarmonyPrefix]
    [HarmonyPatch(typeof(RSACryptoServiceProvider), nameof(RSACryptoServiceProvider.VerifyData))]
    private static bool VerifyDataPrefix(ref bool __result) => ForceVerifyTrue(ref __result);

    [HarmonyPrefix]
    [HarmonyPatch(typeof(RSACryptoServiceProvider), nameof(RSACryptoServiceProvider.VerifyHash),
        [typeof(Il2CppStructArray<byte>), typeof(int), typeof(Il2CppStructArray<byte>)])]
    private static bool VerifyHashPrefix(ref bool __result) => ForceVerifyTrue(ref __result);

    [HarmonyPrefix]
    [HarmonyPatch(typeof(RSACryptoServiceProvider), nameof(RSACryptoServiceProvider.VerifyHash),
        [typeof(Il2CppStructArray<byte>), typeof(Il2CppStructArray<byte>), typeof(HashAlgorithmName),
         typeof(RSASignaturePadding)])]
    private static bool VerifyHashPaddingPrefix(ref bool __result) => ForceVerifyTrue(ref __result);
}
