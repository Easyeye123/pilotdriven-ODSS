# Fleet effectivity registers

Depressurisation charts are effectivity-scoped: a chart is published for one or
more airframe variants, and it applies to an aircraft only when that aircraft's
variant is one of them. To decide that, the engine has to turn a registration
into variant tags.

That mapping is **operator data, not engine logic**. The process below is the
same for every airline; only the files change.

## Process (code — identical for all tenants)

1. Read registration and aircraft type from the CFP.
2. Resolve variant tags from the fleet register, longest prefix wins.
3. A profile applies when it is tagged `ALL`, or when its tags intersect the
   resolved tags.
4. Match the applicable profiles against the filed route.
5. If the registration series is not in any register, resolve no variant and
   report an **effectivity conflict** — never guess, never substitute a chart.

## Adding another airline

Two pieces of data, no code change:

1. A depressurisation index for that operator, mounted at
   `ODSS_DEPRESS_PROFILE_INDEX_S3_URI` or `ODSS_DEPRESS_PROFILE_INDEX_PATH`.
2. A fleet register mounted at `ODSS_FLEET_EFFECTIVITY_PATH`, using whatever
   variant tags that operator's own charts are tagged with.

```json
{
  "schema_version": 1,
  "operator": "Example Airways",
  "registration_series": {
    "G-AB": ["FLEETA", "FLEETB"],
    "N7": "FLEETB"
  }
}
```

A series may map to a single variant or to several. Prefixes are compared with
punctuation removed, so `G-AB` and `GAB` behave identically and any national
registration format works.

A mounted register is authoritative: where it names a series, it replaces the
shipped entry for that series. Everything it does not name still resolves from
the shipped default.

`default-fleet-effectivity.json` in this directory is the shipped register for
the fleet this deployment already carries charts for.
