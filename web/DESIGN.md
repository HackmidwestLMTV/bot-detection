# Follow It visual system

The ticket experience and agent lab share `static/design-system.css`. Components
use semantic color variables instead of independent page palettes: paper surfaces,
dark ink, burnt orange for brand/action, blue for the defending agent, red for the
attacking agent, and green for verified outcomes. Status always includes text.

## Typography and layout

- System sans stack keeps rendering local, fast, and independent of font services.
- Display headings use tight tracking; operational values and identifiers use monospace.
- Ticket checkout uses a two-column event/verification layout above 700 px.
- Lab evidence uses a two-column workspace above 1000 px, with a dedicated decision area.
- Panels share an 18 px radius and quiet borders. Controls target at least 44 px height.
- Content, canvas geometry, and flow stay usable at narrow phone widths.

## Interaction and evidence

- Keyboard users can skip navigation. Every control has visible focus styling.
- Reduced-motion users take the browser check; CSS suppresses optional animation.
- The movement canvas retains its 600 × 400 logical coordinate mapping with no padding/border.
- Lab counts come from API health and gate data. Missing coverage is labeled untested.
- Replay is conspicuously labeled and all mutation controls are disabled.
- Run controls remain disabled until the event connection is established.
- Errors, queue confirmation, and decisions use live status regions.
- Ticket reservations are explicitly a demo with no payment collected.
- Akamai compute, database, storage, and hosted inference appear as the intended
  architecture; UI connection status is not proof of a cloud deployment.

## Checks

`node --test web/tests/*.test.*` exercises real ticket-controller transitions,
worker hashing, evidence display, and missing-device semantics. Browser checks
cover desktop/phone layout, lab authentication, skip → proof of work → reservation,
and single-use pass behavior. API and database tests remain separate from these
visual/controller checks.
