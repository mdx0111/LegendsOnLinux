# xgameruntime: XGameSave is not implemented (Minecraft Legends hangs on "Loading, please wait")

## Summary

`QueryApiImpl` has no handler for the XGameSave runtime class, so titles that
use XGameSave get `E_NOTIMPL` and stall. Minecraft Legends (Microsoft Store /
GDK build `1.18.19068.0`, TitleId `0x61B215AE`) signs in and then waits on
"Loading, please wait" forever:

```
err:xgameruntime:query_api_result unsupported GDK QueryApiImpl class {704c3f58-e629-4cc2-b197-30511b996fe2}, interface {704c3f58-e629-4cc2-b197-30511b996ee2}, hr 0x80004001.
```

The request comes immediately after `XUserAddAsync` returns a user. That
matches `XGameSaveInitializeProvider(user, scid, …)`, which titles call right
after sign-in. Signed out, Legends never gets that far: it loops on its
sign-in dialog. So for this title there is no workaround short of
implementing the API.

I implemented XGameSave on local storage on top of a WineGDK-based engine
(see "Reference implementation" below), and Legends now loads, plays and
saves. Below is everything I had to work out, so it can be done upstream in
whatever form fits the current tree.

## Runtime class and interface

| | GUID |
|---|---|
| runtimeClassId | `{704c3f58-e629-4cc2-b197-30511b996fe2}` |
| interfaceId | `{704c3f58-e629-4cc2-b197-30511b996ee2}` (differs only in the second-to-last byte: `0x6f` vs `0x6e`) |

## Vtable layout

The title reaches XGameSave through small `xgameruntime.lib` thunks. Each one
calls `QueryApiImpl` for the class above, then one vtable slot, then
`Release` (slot 2). Legends contains 18 such thunks. Their argument
shapes match `XGameSave.h` exactly when **slot = 3 + the function's position
in the header**:

| Slot | Function | Used by Legends |
|---:|---|:---:|
| 3 | `XGameSaveInitializeProvider(XUserHandle, const char* scid, bool syncOnDemand, XGameSaveProviderHandle*)` | ✓ |
| 4 | `XGameSaveInitializeProviderAsync(XUserHandle, const char* scid, bool syncOnDemand, XAsyncBlock*)` | |
| 5 | `XGameSaveInitializeProviderResult(XAsyncBlock*, XGameSaveProviderHandle*)` | |
| 6 | `XGameSaveCloseProvider(XGameSaveProviderHandle)` → `void` | |
| 7 | `XGameSaveGetRemainingQuota(XGameSaveProviderHandle, int64_t*)` | ✓ |
| 8 | `XGameSaveGetRemainingQuotaAsync(XGameSaveProviderHandle, XAsyncBlock*)` | ✓ |
| 9 | `XGameSaveGetRemainingQuotaResult(XAsyncBlock*, int64_t*)` | ✓ |
| 10 | `XGameSaveDeleteContainer(XGameSaveProviderHandle, const char* name)` | |
| 11 | `XGameSaveDeleteContainerAsync(XGameSaveProviderHandle, const char* name, XAsyncBlock*)` | ✓ |
| 12 | `XGameSaveDeleteContainerResult(XAsyncBlock*)` | ✓ |
| 13 | `XGameSaveGetContainerInfo(XGameSaveProviderHandle, const char* name, void* context, XGameSaveContainerInfoCallback*)` | |
| 14 | `XGameSaveEnumerateContainerInfo(XGameSaveProviderHandle, void* context, XGameSaveContainerInfoCallback*)` | ✓ |
| 15 | `XGameSaveEnumerateContainerInfoByName(XGameSaveProviderHandle, const char* prefix, void* context, XGameSaveContainerInfoCallback*)` | |
| 16 | `XGameSaveCreateContainer(XGameSaveProviderHandle, const char* name, XGameSaveContainerHandle*)` | ✓ |
| 17 | `XGameSaveCloseContainer(XGameSaveContainerHandle)` → `void` | ✓ |
| 18 | `XGameSaveEnumerateBlobInfo(XGameSaveContainerHandle, void* context, XGameSaveBlobInfoCallback*)` | |
| 19 | `XGameSaveEnumerateBlobInfoByName(XGameSaveContainerHandle, const char* prefix, void* context, XGameSaveBlobInfoCallback*)` | |
| 20 | `XGameSaveReadBlobData(XGameSaveContainerHandle, const char** names, uint32_t* count, size_t blobsSize, XGameSaveBlob*)` | |
| 21 | `XGameSaveReadBlobDataAsync(XGameSaveContainerHandle, const char** names, uint32_t count, XAsyncBlock*)` | ✓ |
| 22 | `XGameSaveReadBlobDataResult(XAsyncBlock*, size_t blobsSize, XGameSaveBlob*, uint32_t* count)` | ✓ |
| 23 | `XGameSaveCreateUpdate(XGameSaveContainerHandle, const char* displayName, XGameSaveUpdateHandle*)` | ✓ |
| 24 | `XGameSaveCloseUpdate(XGameSaveUpdateHandle)` → `void` | ✓ |
| 25 | `XGameSaveSubmitBlobWrite(XGameSaveUpdateHandle, const char* name, const uint8_t* data, size_t size)` | ✓ |
| 26 | `XGameSaveSubmitBlobDelete(XGameSaveUpdateHandle, const char* name)` | ✓ |
| 27 | `XGameSaveSubmitUpdate(XGameSaveUpdateHandle)` | ✓ |
| 28 | `XGameSaveSubmitUpdateAsync(XGameSaveUpdateHandle, XAsyncBlock*)` | ✓ |
| 29 | `XGameSaveSubmitUpdateResult(XAsyncBlock*)` | ✓ |

Checkpoints that pin the order down:

- slot 3 passes a byte-sized third argument (`mov %sil,%r9b`), the `bool`;
- slots 17 and 24 are the only `void` thunks (they discard `eax`);
- slot 21 passes a 32-bit third argument (`mov %esi,%r9d`), `uint32_t countOfBlobs`;
- slots 21, 22 and 25 pass a fourth argument on the stack;
- `XGameSaveReadBlobDataResult` (slot 22) takes 4 arguments, not 5, matching
  the documented signature.

The 9 unused slots follow from the same rule and from their documented
signatures; Legends does not exercise them.

## Structures (x64)

```c
typedef struct XGameSaveBlobInfo { const char *name; uint32_t size; } XGameSaveBlobInfo;            /* 16 bytes */
typedef struct XGameSaveBlob { XGameSaveBlobInfo info; uint8_t *data; } XGameSaveBlob;               /* 24 bytes */
typedef struct XGameSaveContainerInfo
{
    const char *name;
    const char *displayName;
    uint32_t blobCount;
    uint64_t totalSize;
    time_t lastModifiedTime;
    bool needsSync;
} XGameSaveContainerInfo;                                                                            /* 48 bytes */

typedef bool XGameSaveContainerInfoCallback( const XGameSaveContainerInfo *info, void *context );
typedef bool XGameSaveBlobInfoCallback( const XGameSaveBlobInfo *info, void *context );
```

The callbacks return a C++ `bool`, so only `al` is meaningful.

`E_GS_*` codes are `0x80830001` (`E_GS_INVALID_CONTAINER_NAME`) through
`0x8083000F` (`E_GS_PROVIDER_MISMATCH`), as listed on Microsoft Learn; they
are not in `include/xgameerr.h` yet.

## Async calls must use the native XAsync implementation

`QueryApiImpl` hands titles the native `xgameruntime.dll.threading` for
`CLSID_XThreadingImpl`. The `XAsyncGetStatus` / `XAsyncGetResultSize` /
`XAsyncGetResult` a title calls on an async block therefore run in native
code, and expect native async state inside the block.

This matters for XGameSave because the documented read pattern sizes its
buffer with `XAsyncGetResultSize` before calling
`XGameSaveReadBlobDataResult`. An operation begun on Wine's own XAsync
leaves state in the block that the native `XAsyncGetResultSize` cannot read.
I begin, schedule, complete and fetch results for all XGameSave async
operations through the native `IXThreadingImpl` (`XAsyncBegin`,
`XAsyncSchedule`, `XAsyncComplete`, `XAsyncGetResult`). With that, the title's
own XAsync calls work unchanged. Without the native sidecar it falls back to
the built-in XAsync.

## `XGameSaveReadBlobDataResult` buffer layout

The caller allocates one buffer of the size `XAsyncGetResultSize` reports,
and the result must be self-contained. I lay it out as the `XGameSaveBlob`
array first, then each blob's NUL-terminated name and data, with the array
pointing into the same buffer:

```
required = count * sizeof(XGameSaveBlob) + Σ (strlen(name) + 1 + size)
```

The count can then be recovered from the layout (the first name starts right
after the array), so no state has to survive the `GetResult` step.
`blobNames == NULL` or `countOfBlobs == 0` reads every blob in the container.
A missing named blob is `E_GS_BLOB_NOT_FOUND`. I have not checked these
against Windows; they are what the documentation implies and what Legends
accepts.

## What Legends does with it

- SCID: `00000000-0000-0000-0000-000061b215ae` (zeros plus the TitleId).
- Containers are named with a base64 encoding of a file path, e.g.
  `bWluZWNyYWZ0cGUvb3B0aW9ucy50eHQ` with display name
  `minecraftpe/options.txt`, each holding one blob, `blob_0`. The game uses
  XGameSave as a small filesystem.
- At startup it calls `InitializeProvider` → `EnumerateContainerInfo` →
  `GetRemainingQuota`, then repeatedly rewrites its options and telemetry containers
  through `CreateUpdate` / `SubmitBlobWrite` / `SubmitUpdateAsync` while it
  runs.

## Reference implementation

A working C implementation (about 1,180 lines) is in
[`0002-xgameruntime-Implement-XGameSave-on-local-storage.patch`](https://github.com/mdx0111/LegendsOnLinux/blob/main/engine/patches/0002-xgameruntime-Implement-XGameSave-on-local-storage.patch)
of [LegendsOnLinux](https://github.com/mdx0111/LegendsOnLinux). It applies to commit
`75637b6` plus BedrockOnLinux's native5 patches, not to current `master`, and
it hooks into `QueryApiImpl` the way that tree's XStore stub does. The design:

- containers are directories and blobs are files under
  `%LOCALAPPDATA%\WineGDK\XGameSave\<SCID>\`, with names percent-encoded so
  `/` and other characters are safe;
- updates are staged into temporary files, then renamed into place, so a
  failed update leaves the container as it was;
- `needsSync` is always false; there is no cloud sync;
- the quota is a fixed 256 MiB minus what is stored.

Before it could go upstream I would expect to:

- port it to `master`'s C++ structure, with an `IXGameSaveImpl` interface in
  `provider.idl`;
- key storage by the user's XUID as well as the SCID;
- verify `GetContainerInfo` for a missing container, the sync
  `ReadBlobData` size rule and enumeration order against Windows;
- add tests to `dlls/xgameruntime/tests/`.

I'm happy to do that port and open a PR if this direction suits you. If you
already have a different shape in mind for storage (for example going through
the Xodus service), the slot map and the async notes above should still save
some reverse-engineering.

## Related: `XStoreGameLicense` is 104 bytes

Legends also blocks its first loading screen until
`XStoreQueryGameLicenseAsync` reports an active license. When that gets
implemented, note that `XStoreGameLicense` is **104 bytes** on x64
(`STORE_SKU_ID_SIZE` 18, `TRIAL_UNIQUE_ID_MAX_SIZE` 64). An older stub in a
downstream tree wrote 144 bytes, assuming a 64-byte SKU, which overruns the
caller's buffer.
