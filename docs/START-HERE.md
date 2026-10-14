# STL to CAD Converter: start here

**Continuing this tool? Read [the detailed handover](HANDOVER.md).** For pictures and operation, use the [manual](USER-MANUAL.md) and [offline demo](../demo.html).

Converts triangle meshes into CAD boundary geometry. Faceted conversion follows triangles; analytic/arcwise reconstruction is experimental and may leave open edges.

**Start with:** Convert a first part. Start with a small, closed STL whose scale you know. Keep the original unchanged.

**Source:** this is a private source checkpoint, not a live-system mirror. Check [the source manifest](../SOURCE-MANIFEST.json) and current working files before merging.

**Keep your work safe:** Treat conversion jobs as temporary working results and download the outputs you need. The source repository does not contain uploaded meshes or the NAS job store. Back up original meshes independently.

**Next maintainer action:** Run primitive/round-trip fixtures in the actual CAD environment and inspect topology/deviation for representative meshes. Preserve source meshes before decimation; do not promise the original CAD feature tree or analytic success for every mesh.

**Status:** private upload verified on 14 October 2026. These guides accompany the source package. Live runtime, data backups and full recovery were not retested. Public sharing was authorised on 14 October 2026; the NAS backup remains private.
