# Media intake

This context tracks whether a submitted video asset matches an example
delivery policy.

## Language

**Intake decision**

A saved policy outcome and the reasons behind it for one submitted video.

**Declared metadata**

A caller's description of the video's container and codec.

**Inspected metadata**

The container and codec identified from the uploaded video.

**Ready**

A decision whose declared or inspected metadata matches the example delivery
policy. For declared metadata, this checks the caller's description without
inspecting a file. Ready is not a full decode or integrity guarantee.

**Needs review**

A decision whose declared or inspected metadata has at least one mismatch
under the example delivery policy.
