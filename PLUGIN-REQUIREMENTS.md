# Plugin requirements

Status: proposed requirements for the next implementation change. These are acceptance
targets, not a description of capabilities already delivered. Discussion precedes API design.

The existing `Source` interface already accepts string locators and allows plugins to handle
them before file reading. Supporting audio selectors therefore does not, by itself, require
new core methods. The first implementation pass should make this boundary explicit and test
replacement before introducing a new execution abstraction.

Memory happens through ordinary work. A plugin must be useful without asking a person or
acting agent to write an additional memory record after each action. Capturing context
automatically still costs resources; that cost must be visible and controllable.

## Cases the boundary must support

| Case | What should be possible |
| --- | --- |
| Code comments | Find comments, read surrounding code, and consult revision history when needed. Replace a literal reader with a better one without changing the core. |
| Recorded voice | Find a relevant passage in an existing recording and return a reference to its time interval. A transcript is an optional derived representation, with a route back to the recording. |
| Improved transcription | Read the same audio through another implementation without rewriting the original or silently treating the two transcripts as independent witnesses. |
| Composed recall | Feed findings from one operation into another, possibly changing the next operation after inspecting results. The caller may be an agent or a program. |
| Local model | Use a model to select or interpret fragments without making a model service compulsory for other readers. |

Searching voice does not necessarily mean speaking the query. Text search over a transcript
and an audio query are distinct capabilities; neither should be silently assumed.

## Independence and replacement

- A third party can develop, test, and select an implementation without editing core code.
- A plugin declares its identity, implementation version, supported contract version,
  operations, configuration, and external dependencies. Configuration selects the implementation;
  missing capabilities and incompatible versions produce actionable errors.
- A plugin implements the operations it supports. It need not pretend to offer a chronological
  feed, keyword search, or file reading when those concepts do not fit its source.
- Replacing an implementation leaves ordinary source material intact. Derived caches are
  optional and distinguishable from originals; their compatibility is explicit.
- Operation semantics survive replacement; output quality need not be identical. Tests must
  exercise a separately supplied implementation, not just built-in subclasses.

## Addressing and evidence

- Addresses belong to the source reader. Core code must not interpret every address as a
  filesystem path or every fragment as a range of text lines. A revision, message, text span,
  or audio interval must be representable without source-specific branches in the core.
- A result carries enough origin information to revisit its evidence: source reference,
  fragment selector where applicable, and version or observation information when available.
  If the source cannot provide a stable version, the result must not imply repeatability.
- Source content, transformations, and interpretive claims remain distinguishable. Derived
  output retains references to its inputs and the producing operation/implementation. Unknown
  origin is permitted; fabricated certainty is not.
- Source event time, capture time, and processing time are different facts. Missing event time
  must not quietly become file modification time under the same label.
- Verbatim agreement is not proof that a source is true; a source citation is not proof that
  an interpretation follows. The contract must preserve that distinction.

PROV is a candidate vocabulary for expressing these relationships, not a requirement to
maintain a graph database or annotate ordinary actions. A normalized exchange format does
not require sources to adopt a normalized storage format.

## Composition, cost, and failure

- Operations expose usable inputs and outputs so callers can compose them without scraping
  human-readable display text. Reading a source and transforming findings are both valid work.
- Expensive work such as transcription or model inference can be requested explicitly;
  ordinary discovery must not silently start an unbounded processing job.
- The caller can bound work and returned material, and observe partial results, truncation,
  unsupported operations, dependency failures, and cancellation outcomes. An empty result must
  not silently mean the plugin failed. Budget units must be explicit.
- Streaming and batching must be possible without requiring the entire corpus in memory.
  The caller chooses the recall route; the contract does not require an autonomous planner.
- Access restrictions apply to excerpts and derived information as well as originals.
  Combining sources cannot silently shed their restrictions. Running arbitrary plugin code
  in-process is not a security sandbox; installation and execution trust remain separate concerns.

## First refactor

Document and validate the existing result shapes, operation semantics, and supported extension
imports. Separate public plugin API from private core helpers. Specify which operations are
optional, how their absence is reported, and what each time and budget field means. Preserve
opaque locators; introduce new methods only where the acceptance cases cannot use existing ones.

A prepared transcript is one valid implementation of voice recall. Another may transcribe a
selected interval on demand. The contract must not require all interpretation to happen offline;
the first pass need not implement a general transformation scheduler.

## Acceptance

Use synthetic fixtures, not personal recordings or conversation archives.

1. Supply two independent comment readers through configuration. Replace one with the other;
   the same caller can use their results and revisit the supporting code without core edits.
2. Use an audio fixture and a deterministic test transcript provider. Search returns a passage
   with an audio interval and a traceable transcription result. Replacing the provider preserves
   the audio reference. This tests the interface, not speech-recognition quality.
3. Compose a source read with a separate transformation and revisit the original evidence.
   Change the second operation based on the first result without altering the core.
4. Exercise missing dependencies, incompatible versions, partial output, a failing plugin,
   changed source content, and a restricted source. Verify that these are distinguishable from
   a successful search with no matches and that restrictions survive the composed path.
5. Keep existing supported recall entry points working during migration. A repository change
   does not update an installed copy or restart a running service.

These cases set the boundary. They do not require a plugin marketplace, an automatic plugin
updater, a production speech recognizer, or a general workflow language in the first refactor.
