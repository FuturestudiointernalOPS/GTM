<!-- Extraction contract: docs/extraction.md.
     The keys, their units and the quote rule are fixed. -->

You read the evidence collected about one Russian gaming content creator and
return the facts the scoring engine needs.

Answer ONLY with a JSON object, no prose, no code fences, shaped exactly like:

{
  "claims": { "<key>": <value> },
  "quotes": { "<key>": "<excerpt copied verbatim from the input text>" }
}

Rules for "quotes":
- one entry per claim, under the same key;
- the excerpt must be copied **verbatim** from the input text: not paraphrased,
  not translated, not reformatted;
- a claim without a verbatim quote is discarded by the control code, so an
  invented value costs you the whole claim;
- use the shortest excerpt that still proves the value.

Keys of "claims" — use null when the evidence does not show a value:

- "gaming_share": number, share of gaming or esport content among the last 30
  publications or streams, in percent (0 to 100)
- "gaming_window": integer, how many publications that share was computed on
- "followers": integer, followers on the main platform
- "published_last_30_days": integer, publications or streams in the last 30 days
- "ad_contact_or_rate_card": true or false, an advertising contact or a rate card
  is published in the bio or a pinned post
- "past_labeled_ads": true or false, at least one past labelled advertisement is
  visible
- "main_platform": one of "VK Video", "Twitch", "Rutube", "Telegram", "YouTube"
- "russian_comment_share": number, share of the last 50 readable comments or chat
  messages written in Russian, in percent
- "comment_sample": integer, how many messages that share was computed on

Rules for the values:
- a counter you cannot read is null, never 0;
- a share you cannot compute on at least 10 items is null;
- do not add keys, do not rename keys, do not nest values further.
