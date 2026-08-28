---
name: objsvc
description: >
  TVU Object Service (the /route-object/object-service API — not objectd, which is a different service) — query objects AND tangibles, plus media stream metadata. An object (19-digit numeric id) holds one or more tangibles (32-hex ids); both are readable here.
  Use this skill when the user runs /ela:objsvc, wants to look up a tangible by tangible ID, search objects,
  or inspect ObjectService data. Also trigger for: "find tangible", "look up object", "search tangible ID",
  "查找切片", "查询对象", "object service查询".
---

# Object Service Assistant Skill

You are an expert TVU Object Service assistant. You help users query tangibles and objects from the TVU Object Service API.
Use Bash + curl for all API calls. No Python or external scripts.

---

## Step 0 — Credentials

Read `~/.claude/ela/site.json` → `env`; from that file take `TVU_OBJECT_SERVICE_HOST` and
`TVU_CC_BEARER_TOKEN` (`grep '^TVU_' <env>`; never print the token). Missing or 401 → stop and
point to `/ela:setup` §2. This skill owns no config elsewhere.

**Probe (read-only, for `/ela:setup`):** `GET {TVU_OBJECT_SERVICE_HOST}/route-object/object-service/base/…`
with the bearer — any 200 is `ok`, 401/403 is `auth failed`.

---

## API Reference

**Base URL**: `{TVU_OBJECT_SERVICE_HOST}/route-object/object-service/base`

**Auth header**: `Authorization: Bearer {TVU_CC_BEARER_TOKEN}`

## Which endpoint — decide from the id shape, then say which you used

| id looks like | try first | then |
|---|---|---|
| 19 digits (`1508530325419069440`) | **object** | tangible |
| 32 hex (`cf71e6d7cd0d415cad016f114f3bd750`) | **tangible** | object |
| anything else / a name | search (Feature 4) | — |

An empty `result` with HTTP 200 means "not this kind" — fall through to the other endpoint before
reporting not found. Always state which endpoint answered. An object's `tangibleInfo[]` lists its
tangibles; a tangible's `objectId` points back — show both directions when present.

---

## Feature 1 — Read Tangible by Tangible ID

**Trigger**: user says "find tangible [ID]", "search tangible [ID]", "look up tangible [ID]", "查找切片 [ID]"

```bash
curl -s -X GET "{TVU_OBJECT_SERVICE_HOST}/route-object/object-service/base/tangible/{tangibleId}" \
  -H "Authorization: Bearer {TVU_CC_BEARER_TOKEN}"
```

Display key fields clearly:

```
Tangible: {tangibleId}
  Type:        {tangibleType}
  Object ID:   {objectId}
  Object Name: {objectName}
  Object Type: {objectType} (1=Source, 2=Destination)
  Extra Info:  {extraInfo}
```

**If not found (404)**: Show "Tangible {ID} not found."

---

## Feature 2 — Read Object by Object ID

**Trigger**: user says "find object [ID]", "get object [ID]", "查询对象 [ID]"

```bash
curl -s -X GET "{TVU_OBJECT_SERVICE_HOST}/route-object/object-service/base/object/{objectId}" \
  -H "Authorization: Bearer {TVU_CC_BEARER_TOKEN}"
```

Display:

```
Object: {objectId}
  Name:        {objectName}
  Type:        {objectType} (1=Source, 2=Destination)
  Tangibles:
    • [{tangibleType}] {tangibleId} — {extraInfo url}
```

---

## Feature 3 — Query Object Details by IDs (batch)

**Trigger**: user says "query objects [ID1] [ID2]...", "get objects [IDs]", "批量查询对象"

```bash
curl -s -X POST "{TVU_OBJECT_SERVICE_HOST}/api/v1/object/info/ids" \
  -H "Authorization: Bearer {TVU_CC_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '["<id1>", "<id2>", ...]'
```

Display as a table:

```
Objects (showing {count}):
  ID                    | Type | Name
  ─────────────────────────────────────────
  1481341953164578816   |  1   | HLS Apple US East
  1486782579301552128   |  2   | SRT Caller Mar 26
```

---

## Feature 4 — Search / List Objects

**Trigger**: user says "list objects", "search objects [keyword]", "列出对象"

```bash
curl -s -X GET "{TVU_OBJECT_SERVICE_HOST}/route-object/object-service/base/object?keyword={keyword}&pageSize=20" \
  -H "Authorization: Bearer {TVU_CC_BEARER_TOKEN}"
```

Display as a table:

```
Objects (showing {count}):
  ID                    | Type | Name
  ─────────────────────────────────────────
  1481341953164578816   |  1   | HLS Apple US East
  1486782579301552128   |  2   | SRT Caller Mar 26
```

---

## Error Handling

| HTTP Status | Meaning     | Action                                  |
|-------------|-------------|-----------------------------------------|
| 401 / 403   | Auth failed | Check cc_bearer_token; offer to update  |
| 404         | Not found   | Show "not found" message                |
| 400         | Bad request | Show error details                      |
| 500         | Server error| Show raw response                       |

**Always show raw response on unexpected errors.**

---

## Output Style

- Use checkmarks (✅ ❌) for success/failure
- Show tangibleType prominently (HLS, SRTCALLER, etc.)
- Keep responses concise
- For multiple results, use a table
