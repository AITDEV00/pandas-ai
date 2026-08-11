# Architecture

Internal architecture notes for the chat-excel-server and the code-generation
pipeline.

| Page | Purpose |
|------|---------|
| [Vertical Slice & Server](server.md) | Server layout under `server/features/`, core shared modules, registration |
| [Code Generation Pipeline](codegen-pipeline.md) | How natural-language queries become Python+SQL, and where validation runs |
| [Concurrent Registration Logic Map](concurrent-registration-logic-map.md) | Trace of the registration flow that maps to the root-cause register |