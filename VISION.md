# Why memory happens

Memory happens through ordinary activity. Creating a file, discussing a problem,
changing an approach or abandoning an attempt leaves information we can return to.
Our aim is to make those traces available for later understanding without requiring
a separate act of remembering to write memory down.

This is our design position. The [README](README.md) and issues describe what the
implementation currently supports and where it falls short. The [FAQ](FAQ.md)
explores the implications through concrete questions.

## Let ordinary work leave richer traces

A file and its creation time say little about intent. A related request, revision
and surrounding attempts can supply more context. One direction of development is
to retain that information and its connections through the ordinary workflow,
without requiring people to maintain a parallel account of their work.

## Learn to read the traces

The other direction is better reading: finding and connecting what remains, while
distinguishing observed events from inferred intentions. Richer records and better
reading are separate problems. Unsupported explanations should remain unknowns.

A summary records someone's understanding at a particular time. Making it the sole
basis of recall binds future questions to that earlier selection. We want to retain
the possibility of new understanding when a task makes a previously minor detail relevant.

## Recall is a workflow

We want a source to become usable through a plugin that knows how to read it where
it already lives: a Git history, a Markdown folder, or another record of activity.
Loading everything into a separate memory database should be optional.

Readers expose streams; mappers extract or transform information; reducers select
or combine it for the task. A recall workflow composes these steps and may change
direction as it finds evidence. The question itself may still be forming. New ways
of reading and new compositions should let the system grow.

A local model can participate as a mapper or reducer when its interpretation is
useful. Ordinary code may be sufficient for other steps. Indexes and caches can
reduce repeated work. Each is a tool whose value and cost we need to establish.

## Keep recollection open to correction

A faithful record preserves what was said or done, including mistaken beliefs.
It remains a record of that time as understanding changes. Reading it now introduces
a new interpretation that can be wrong; this asymmetry matters to how we evaluate
recall. A proposal, an experiment and an accepted decision carry different weight.

Interpretations should keep a way back to their evidence, where access and retention
permit. Conflicts and gaps should remain visible. Empty searches, unavailable sources
and access restrictions must be distinguishable without exposing protected contents.

## Attention is part of the cost

A result spends the reader's time and context. Start with enough to choose what to
open, then allow deeper reading. Output and machinery should earn their cost through
usefulness. We want complexity to be an explicit engineering choice.

The owner of a trace controls what may be shared; technical reachability does not
establish permission. Enforcement needs testing, with limitations stated openly.

## Judge memory by the work it helps resume

Can a fresh session recover a useful thread, preserve its meaning and continue work
with less reconstruction by the human? A confident but mistaken account is a failure
even when retrieval itself worked.

People and agents using the tool should be able to report those failures, propose
changes and review each other's work directly. These principles can change too:
experience should give us grounds to revise them.
