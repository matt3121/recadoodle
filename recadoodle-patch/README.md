# Recadoodle client patch

A [BepInEx 6](https://github.com/BepInEx/BepInEx) IL2CPP plugin that connects the April 2023 Rec Room client to a Recadoodle server.

The patch redirects RecNet requests, supplies custom Photon credentials, supports server-hosted images, and includes the new watch menu, dark UI, admin menu, and Maker Pen permission features.

> This client patch disables anti-cheat, certificate validation, and RSA signature verification. Use it only with a server you trust.

## Requirements

- The Rec Room `20230414` build from DepotDownloader manifest `6426603215211043630`
- BepInEx 6 for IL2CPP, launched once to generate `BepInEx/interop`
- The .NET 6 SDK
- A running Recadoodle server and your Photon Realtime, Voice, and Chat app IDs

## Build

Copy the game-path template and set it to your Rec Room installation:

```powershell
Copy-Item GamePath.props.example GamePath.props
dotnet build
```

`GamePath.props` stays local and is ignored by Git. The build copies `Recadoodle.dll` into `BepInEx/plugins`. Close Rec Room before building if Windows reports that the DLL is locked.

To compile without copying the DLL into the game, run `dotnet build -p:DeployAfterBuild=false`.

## Configure

Launch the game once after installing the plugin, then edit:

```text
BepInEx/config/recadoodle.patch.cfg
```

For a Recadoodle server running with the repository's normal local setup, use:

```ini
[Server]
RecNet NameServer Host = http://127.0.0.1:5000
```

Add your own Photon IDs under `[Photon]`. Do not commit the generated configuration because it contains credentials.

The included `recadoodle.patch.cfg.example` lists every supported option. Localhost uses HTTP by default, which avoids legacy-client TLS handshake failures from a local HTTPS certificate.

## Features

| Feature | Main source |
| --- | --- |
| Recadoodle server redirect and request logging | `Patches/SendRequestPatch.cs` |
| Photon app and name-server overrides | `Patches/PhotonPatches.cs` |
| Server-hosted profile and content images | `Patches/ImageSigningPatch.cs` |
| New watch menu and theme controls | `Patches/NewWatchMenuPatch.cs`, `Patches/DarkUIController.cs` |
| F8 admin menu | `Patches/AdminMenuController.cs` |
| Maker Pen permission support | `Patches/MakerPenPermissionPatch.cs` |
| DUID mismatch workaround and diagnostics | `Patches/DUIDMismatchPatch.cs` and related DUID patches |
| EAC and TLS compatibility patches | `Patches/EACPatches.cs`, `Patches/DisableTLSPinning.cs` |

## Source

The patch is maintained in the [`client-patch`](https://github.com/matt3121/recadoodle/tree/client-patch/recadoodle-patch) branch of Recadoodle.

Based on [CannedNet.Client](https://github.com/CannedNet/CannedNet.Client). The original copyright and attribution are retained in [LICENSE](LICENSE) and [NOTICES](NOTICES).

## License

[MIT](LICENSE)
