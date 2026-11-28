# Structured Output Schema

`twitter-cli` uses a shared agent-friendly envelope for machine-readable output.

## Success

```yaml
ok: true
schema_version: "1"
data: ...
pagination:
  nextCursor: "optional-cursor"
```

## Error

```yaml
ok: false
schema_version: "1"
error:
  code: api_error
  message: User @foo not found
```

## Notes

- `--yaml` and `--json` both use this envelope
- non-TTY stdout defaults to YAML
- tweet and user lists are returned under `data`
- timeline-style list commands (`feed`, `bookmarks`, `list`, `tweet`) may also return `pagination.nextCursor`
- `article` returns a single tweet object under `data`
- `news` returns a list of Explore News story objects (`rank`, `title`, `name`, `category`, `context`, `query`, `url`, `post_count`, `trend_id`, `is_ai_trend`, `type`) under `data`
- `doctor` returns `data.checks` (metadata only — never emits cookies or tokens)
- `status` returns `data.authenticated` plus `data.user`
- `whoami` returns `data.user`
- write commands (`post`, `reply`, `quote`, `article-publish`, etc.) also support explicit `--json` / `--yaml`

## Tweet & Media Fields

Each tweet object in `data` includes:

- `author`: `id`, `name`, `screenName`, `profileImageUrl`, `verified`, `followers`, `following`, plus optional `viewerFollowing` / `viewerFollowedBy` (when present in upstream payload)
- `possiblySensitive`: boolean flag from the tweet payload
- Thread metadata (included when present): `conversationId`, `inReplyToStatusId`, `inReplyToUserId`, `inReplyToScreenName`
- `media[]`: `type`, `url`, `width`, `height`, `adultContent`, `graphicViolence`, `otherWarning`, plus optional `posterUrl`, `altText`, `durationMs`

## Article Fields

`twitter article <id> --json` returns the standard tweet object plus:

```yaml
data:
  id: "1234567890"
  articleTitle: "Article Title"
  articleText: |
    # Heading
    Body text...
```

## Error Codes

Common structured error codes:

- `not_authenticated`
- `not_found`
- `invalid_input`
- `rate_limited`
- `network_error`
- `query_id_error`
- `media_upload_error`
- `api_error`
