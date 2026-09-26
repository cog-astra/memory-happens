# Questions about the design

These answers develop the [vision](VISION.md). Implementation status belongs in
the [README](README.md) and issues; the architecture described here is a direction
for development.

## How does this differ from a vector database?

The architectural aim is to read existing sources through plugins and assemble a
useful view when needed. A Git history or a folder of Markdown should be usable
without first feeding it into a separate database and keeping that copy synchronized.
The workflow may read, transform and combine streams according to the current task.

A vector index is one possible search tool within that workflow. Vector databases
can store source text and metadata alongside vectors; losing historical context is
not an inherent property of them. See, for example, [Qdrant's data model](https://qdrant.tech/documentation/manage-data/points/).
The design choice concerns whether prior ingestion is required for a source to
participate. On-demand reading has its own cost in repeated I/O and computation;
indexes and caches are useful when that cost justifies them.

## Does ordinary activity really leave enough information?

Sometimes a trace records only that an action occurred. A filename and timestamp
cannot establish why the file was created. A request, command intention, revision
and surrounding conversation may already contain more context. One development
direction is to retain those connections through the ordinary workflow.

That takes engineering: source readers, capture where needed, and access rules.
The aim is to avoid making the person maintain a second account of their work.
Reading cannot reliably recover information that was never expressed or retained.

## Can a local model be a mapper or reducer?

Yes, as a design option. A model served through Ollama or another runtime could map
passages to candidate topics with source references, or reduce several findings to
a proposed connection. A later step could inspect the original passages, widen the
search or pursue a different lead. Recall can be a dynamic workflow.

Model output is another interpretation. It should retain its provenance and the
references needed to inspect its basis. Its usefulness, omissions, reading cost and
execution cost need evaluation. A deterministic step may be sufficient; the design
does not require a model call for every source or every stage.

## Can this memory become stale?

A faithful historical record does not need to remain current advice. It can preserve
the fact that someone believed or decided something at a particular time, even when
that belief was mistaken. A summary similarly records an understanding held then.

The reader can still mistake an old decision for a current one, misread an exchange,
or infer an intention the record does not support. Source time and revision, the
surrounding context and later traces help check that reading. Preserving a record
and interpreting it correctly are separate responsibilities; historical framing
does not guarantee correct interpretation.
