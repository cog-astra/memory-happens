# Why memory happens

Memory happens through ordinary activity. Creating a file, discussing a problem,
changing an approach or abandoning an attempt leaves information we can return to.
Our aim is to make those traces available for later understanding without requiring
a separate act of remembering to write memory down.

This is our design position. The [README](README.md) and issues describe what the
implementation currently supports and where it falls short.

## Let ordinary work leave richer traces

A file and its creation time tell us that something happened. They say little about
what prompted it or what the author was trying to achieve. A related request, the
change itself and the surrounding attempts can make more of that context available.

One direction of development is to retain more of the information already present
when an action happens, including its connections to other actions. The ordinary
workflow should carry that context forward. Requiring people to maintain a parallel
account of their work would undermine this aim.

## Learn to read the traces

The other direction is to become better at finding, reading and connecting what
remains. Richer records and better reading are separate problems; improving either
can help. A reader should distinguish an observed event from an inferred intention.
When the traces do not support an explanation, the gap should remain visible.

A summary records how someone understood an episode at a particular time. That is
a useful additional trace, but it selects what mattered to that reader then. Making
it the sole basis of future recall would bind future questions to that earlier
selection. We want to preserve the possibility of understanding the past differently
when a new task makes a previously minor detail relevant.

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
