# DQL Reference (from dynatrace-dql skill)

## DQL Fundamentals

DQL is a pipeline-based query language for Dynatrace Grail storage. Queries chain commands with `|` (pipe). Data flows left-to-right, filtered and transformed at each step.

### Pipeline structure
```
fetch <dataObject> [, from:] [, to:] [, bucket:] [, samplingRatio:]
| filter <condition>
| fieldsAdd <expression>
| summarize <aggregation>, by:{<grouping>}
| sort <field> desc
| limit <n>
```

### Grail data objects
| Data object | Description |
|---|---|
| `logs` | Log records |
| `events` | Generic events |
| `bizevents` | Business events |
| `spans` | Distributed traces |
| `dt.davis.problems` | Davis AI root-cause problems |
| `dt.davis.events` | Davis raw events (CPU saturation, etc.) |
| `dt.davis.events.snapshots` | Point-in-time Davis event snapshots |
| `dt.entity.<type>` | Entity queries (host, service, process_group, etc.) |

For metrics, use `timeseries` starting command instead of `fetch`.

## Recommended Command Order (Performance)
1. **Filter early** — Reduce records immediately after `fetch`
2. **Select fields early** — `fields`, `fieldsKeep`, `fieldsRemove`
3. **Transform** — `fieldsAdd`, `parse`, `append`
4. **Aggregate** — `summarize` or `makeTimeseries`
5. **Sort last** — After aggregation, never right after `fetch`
6. **Limit last** — After `sort`

## Performance Anti-Patterns
- Sort before filter (sorts all data before reducing)
- Transform fields before filtering (transforms every record)
- Negation filters (slower — use `filterOut` instead)
- No time range narrowing (defaults to 2h scan)
- `limit` before `summarize` (aggregates over subset = wrong results)
- `join`/`lookup` for filtering (slow — use enriched fields)

## Key DQL Commands
- `fetch`, `timeseries`, `data record()`
- `filter`, `filterOut`, `search`, `dedup`
- `fields`, `fieldsAdd`, `fieldsKeep`, `fieldsRemove`, `fieldsRename`
- `summarize`, `makeTimeseries`
- `expand`, `fieldsFlatten`, `parse`, `append`
- `lookup`, `join`
- `sort`, `limit`

## String Comparison
- `==` / `!=` — Exact match (case-sensitive)
- `~` — Pattern match with wildcards (`*`)
- `contains()`, `matchesValue()`, `matchesPhrase()`

## Reserved Keywords (must backtick-escape)
`true`, `false`, `null`, `mod`, `and`, `or`, `xor`, `not`

## Entity Name Resolution
```
| fieldsAdd host.name = entityName(dt.entity.host, type:"dt.entity.host")
```

## Time Expressions
| Syntax | Meaning |
|---|---|
| `from:-2h` | Relative: last 2 hours |
| `from:now() - 24h` | Relative with `now()` |
| `from:-1d@d` | Snapped to start of day |
| `from:bin(now(), 24h)` | Binned to 24h boundary |

Duration literals: `s`, `m`, `h`, `d`.

## Common Mistakes
1. Reserved keywords as field names → wrap in backticks
2. Using `~` when `==` suffices → exact match is faster
3. Not expanding arrays before counting → `expand` first
4. Timeseries gaps → use `default:0` and `nonempty:true`
5. Duration in nanoseconds not ms → divide by 3,600,000,000,000 for hours
6. Missing `isNotNull()` on optional fields before aggregation

## Complete Function Catalog

### Aggregation (with summarize/makeTimeseries)
count, countDistinct, countDistinctApprox, countDistinctExact, countIf,
avg, sum, min, max, median, percentile, stddev, variance, correlation,
collectArray, collectDistinct, takeAny, takeFirst, takeLast, takeMax, takeMin

### String
contains, startsWith, endsWith, like, matchesValue, matchesPhrase, matchesPattern,
concat, lower, upper, trim, substring, stringLength, indexOf, lastIndexOf,
replaceString, replacePattern, splitString, splitByPattern, parse, parseAll,
jsonField, jsonPath, levenshteinDistance, punctuation, encodeUrl, decodeUrl,
escape, unescape, unescapeHtml, getCharacter

### Time
now, timestamp, timestampFromUnixMillis/Seconds/Nanos,
unixMillisFromTimestamp/Seconds/Nanos, formatTimestamp,
duration, timeframe, getStart, getEnd,
getYear, getMonth, getDayOfMonth, getDayOfWeek, getDayOfYear,
getWeekOfYear, getHour, getMinute, getSecond

### Array
array, arrayAvg, arrayMax, arrayMin, arrayMedian,
arrayFirst, arrayLast, arrayConcat, arrayDistinct, arrayFlatten,
arrayIndexOf, arrayLastIndexOf, arrayDelta, arrayCumulativeSum,
arrayMovingAvg, arrayMovingMax

### Conditional
if(cond, then, else), coalesce(a, b, ...)

### Boolean
isNull, isNotNull, isTrueOrNull, isFalseOrNull

### IP
isIpAddress, isIpv4, isIpv6, isPrivateIp, isPublicIp,
isLoopbackIp, isLinkLocalIp, ipContains, ipMask

### Hash
crc32, md5, sha1, sha256, sha512

### Conversion
Safe: asString, asLong, asDouble, asBoolean, asTimestamp, asDuration, asTimeframe, asArray, asRecord, asBinary, asIp, asUid
Converting: toString, toLong, toDouble, toBoolean, toTimestamp, toDuration, toTimeframe, toArray, toIp, toUid
Utilities: type(), hexStringToNumber, numberToHexString, encode, decode
