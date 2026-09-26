# Questions about the design

These answers explain the [vision](VISION.md), including proposed capabilities.
They are not an implementation checklist. See the [README](README.md) for status.

## Does "memory happens" mean no work is required?

Building capture and reading tools takes work. Using them should not require a
parallel diary from the human or agent. A note, handoff or commit message is a
valid trace when someone chooses to write it. Recording intent is an opportunity,
not an obligation.

Some traces contain little context. A timestamp cannot establish why a file was
created. Preserve useful context when available; later inference can suggest new
connections, but cannot guarantee recovery of what was never recorded.

## Are you building a knowledge base?

Our aim is to recover material from past activity so it can help now. A useful
result might be a passage, a change, several conflicting accounts, or a reasoned
conclusion. Recall does not have to settle their meaning into a maintained set
of facts before returning anything.

Understanding can be part of the workflow. A powerful model may investigate and
bring back conclusions, much like a delegated researcher. Its conclusions remain
interpretations with a route back to their basis, rather than replacements for it.

The purpose can also be inspiration: "What have I read that evokes this kind of
place?" An associative search can offer material for a new idea without needing
a problem to solve or a single correct answer.

## How does this differ from a vector database?

The design choice is whether a source must be ingested into a separate store
before it can participate. A Git history or Markdown folder should be readable
through a plugin where it already lives.

A vector index can be one search operation in that workflow. Indexes and caches
may justify their cost by avoiding repeated reading.

## What can a plugin contribute?

A plugin can supply several operations, each with its own parameters, rather
than only adding a searchable source. A code-comment reader might extract
comments and return source lines. A voice plugin might read recordings,
transcribe them or retrieve passages from existing transcripts.

Text can use line selectors; recorded audio can use time intervals when those
positions are known. The plugin explains its addressing. Two transcriptions of
one recording remain interpretations of the same source, not independent witnesses.

The goal is for an independently improved operation to replace another compatible
one without rewriting its callers. Common contracts and conformance checks must
make that possible; loading external code alone does not demonstrate it.

## Can recall change direction while it runs?

That is part of the design. For example: read conversations and revisions, gather
related passages, let a model notice that the reason for a decision is missing,
then read an earlier exchange. Another workflow may need only text matching.

A configured route and choosing a continuation during execution are distinct
capabilities. Both are useful. Models, including local ones, may act as mappers,
reducers or planners; no model is required at every step. A minute of useful
investigation can be acceptable while we explore the approach.

Execution should leave enough provenance to inspect how a result arose, without
manual bookkeeping. A reference to a retained file revision may suffice; a
transient response may need capture. Missing records limit later reconstruction.

## How does the system explain what to do next?

We call this self-bootstrap and self-recovery. An operation describes how to use
it at the point of use. On failure it explains what went wrong and offers relevant
ways forward. These descriptions should be brief, with details available on demand.

For an empty search, a possible response is: "No matches in notes. You can try
conversations, a wider date range, or different wording." Those are available
choices, not an instruction to run every one. Having no match is not itself an error.

## What does "nothing comes to mind" mean?

Only that this attempt did not recover a useful result. It does not establish
that something never happened. No matches, an unavailable source and denied access
are different outcomes. Keep the response concise; expose coverage and diagnostic
detail when needed, without revealing protected contents.

## Does every user need a humans.txt file?

No. It is a convention used in our development environment, not a universal
requirement. Source selection and the user's existing access policies should
govern what recall can read. Technical reachability alone is not permission.

## Will it remember things without being asked?

That is outside the current scope. We start with an expressed question, interest
or difficulty and look for relevant past material. Associative search for an idea
is compatible with this: it does not require unsolicited reminders. Predicting
when to offer a reminder could be explored separately; it is not required to make
this approach useful.

## Can a result show how far it is from the original?

One proposal is **derivation depth** for the returned content. Relative to a known
source: an exact excerpt has depth 0, a summary has depth 1, and a summary of that
summary has depth 2. Sorting or filtering need not increase it. A model that merely
chooses where to search does not add a paraphrase to the quotation eventually found.

This is neither a trust score nor a measure of verification effort. An excerpt
can omit a crucial qualification; one summary may combine thousands of records.
Source selection can mislead even when the wording is unchanged. Unknown lineage
must remain unknown rather than silently becoming 0.

Summaries of summaries can be useful, such as a book overview built from chapter
overviews. Depth helps the reader choose whether to inspect earlier material;
it imposes no automatic cutoff. Counting rules for mixed results and branching
chains remain to be tested. The mechanism should derive the indicator from the
actual result and its lineage, without asking someone to maintain it by hand.
