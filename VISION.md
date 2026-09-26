# Why memory happens

Memory happens when something from the past becomes useful in the present.
Our aim is to make that possible during ordinary work, with less effort spent
maintaining memory and more attention available for the work itself.

This is our design position. The [README](README.md) and issues describe what the
implementation currently supports and where it falls short.

## Work should leave enough to return to

Conversations, changes, notes and unfinished attempts leave traces. We want to use
those traces so a person can return to a problem without first reconstructing the
history for an assistant. A handoff or a carefully written note can help, but useful
recall should also be possible when nobody anticipated the next question.

An archive preserves a record. Recall selects and connects parts of that record
for a current purpose. Storing more is useful only when it improves the chance of
finding something worth bringing back.

## The present gives the past its relevance

The same conversation can matter for different reasons on different days. A reader
may need a decision, its motivation, an abandoned approach, or a useful analogy.
Sometimes the question itself is still forming.

We therefore want several ways into the traces: time, words, places, changes and
connections suggested by the reader. Search results and generated topics provide
leads. Understanding the connection remains work for the reader, who should be able
to follow a lead, challenge it, or leave it behind.

## Keep recollection open to correction

A useful recollection should let its reader return to the source and see when and
in what circumstances it was said or done. A proposal, an experiment and an accepted
decision carry different weight. Later evidence can change the meaning of an earlier
statement.

Summaries and interpretations should retain a way back to their evidence, where
access and retention permit. Conflicting traces and unanswered questions deserve to
remain visible. An empty search, an unavailable source and a source the reader may
not access must be distinguishable without exposing protected contents.

## Attention is part of the cost

A result spends the reader's time and context. Start with enough to choose what to
open, then allow deeper reading. More output should earn its cost through usefulness.
The same principle applies to the system: every index, model and layer of machinery
needs a reason to exist. We want complexity to be an explicit engineering choice.

Access is also a condition of relevance. The person who owns a trace controls what
may be shared; being technically reachable does not establish permission. This is
a design commitment whose enforcement needs testing, with limitations stated openly.

## Judge memory by the work it helps resume

We want to test whether a fresh session can recover a useful thread, preserve its
meaning and continue the work with less reconstruction by the human. Finding a
matching phrase is one step toward that outcome. A confident but mistaken account
is a failure even when retrieval itself worked.

People and agents using the tool should be able to report those failures, propose
changes and review each other's work directly. These principles can change too:
experience should give us grounds to revise them.
