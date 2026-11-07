# Native25 build patches

[recipe-24.0.json](../tools/build/recipe-24.0.json) lists the changes used by Native25
and their expected file hashes. It applies to the original upstream revisions in
the [manifest](../manifests/lineage-24.0-candidate.xml).

The patches cover device setup, module/DSP startup, fingerprint, sensors, display,
audio/media compatibility and support for the optional Camera/Photos packages.
[Changes and credits](../../../CHANGES.md) explains their purpose and attribution.

For the maintained component repositories, use the matching manifest repository's
`integration/recipe.json`. Device/common changes are already committed there;
applying the original full recipe again would apply those patches twice.

Files outside the selected recipe are older references. Use the recipe and source
version matching the release you are inspecting. [Sources](../../../SOURCES.md)
provides the release tags and kernel source.
