# ASI Meal Management: UI/UX design specification

**Status:** Proposed for owner review; no UI implementation is authorized by this document. The owner selected a modern internal application with a compact left sidebar.

This specification is based on the current frontend, its documented API contracts, and owner feedback. No browser screenshots or visual verification were performed for this specification. The owner reports that mobile and tablet are generally usable, while desktop and tablet-landscape layouts feel stretched and vertically stacked; search suggestions and more useful, compact report visuals are desired. Treat those observations as input to validate during implementation, not as measurements.

## Principles and information architecture

- Support repetitive operational work: compact sections, clear labels, visible outcomes, and no promotional content or decorative dashboard.
- Preserve the existing workflows, server-calculated values, authorization, same-origin API proxy, session cookies, CSRF protections, and audit behavior. UI visibility is not authorization.
- Use Orders, Menu, Employees, and Reports as the primary destinations. Visitor search and creation belong in order entry. The current Visitors navigation item only opens a deferred-directory placeholder; remove that placeholder from primary navigation when the shell is implemented, without inventing a visitor directory.
- Keep headings and actions close to their content; avoid nested navigation and redundant explanatory paragraphs. Prefer predictable layouts and progressive disclosure for less common actions.
- Apply local Cardo headings and Open Sans body text already imported in [global styles](../apps/web/src/app/globals.css). Do not require external images or meal photography.

## Navigation and shell

- At viewport widths of 1024px and above, use a 216px expanded left sidebar, leaving at least 768px for the workspace at 1024px. Keep identity at the top, four labeled icon links in a vertical list, and the authenticated display name, role, and Sign out at the bottom. Long names wrap; account actions remain visible without overlap. Use a simple label treatment for ASI Meal Management.
- Give the active destination a contrasting surface, a visible edge or marker, and `aria-current`; hover uses a separate subtle surface. Do not convey the active state by color alone. Keyboard focus is distinct from both. Keep full text labels: no collapsed desktop mode in the first implementation.
- Below 1024px, use a header with identity and a labeled Menu button opening a drawer no wider than `min(288px, 85vw)`. Use a named modal dialog, focus the first relevant control on open, trap focus while open, close with Escape or its explicit Close button, and restore focus to the trigger. Prevent background interaction and scrolling while open. Selecting a destination closes the drawer and focuses the destination heading; preserve the skip-to-content link.
- Navigation should not silently lose an in-progress order or uncertain submission. Existing in-memory drafts and retry keys are lost on navigation, reload or sign-out; preserve the existing safe retry semantics and surface this limitation. Assess any navigation guard separately without introducing a new approval workflow.

## Design tokens and controls

Values are implementation targets in CSS variables, not changes made in this stage. Contrast ratios below were calculated for the exact pairs shown; recheck actual hover, focus, disabled, and component combinations.

| Token | Value and use |
| --- | --- |
| Primary | `#160D76`: headings, primary buttons and navigation; white on navy 15.52:1. |
| Secondary | `#4094D9`: information accents, charts and borders; navy text on blue 4.77:1. White on blue is 3.25:1, insufficient for normal text. |
| Accent | `#F08530`: sparingly for New or Refresh; dark `#222222` text on orange 6.14:1. White on orange is 2.59:1 and must not be used for normal button text. |
| Background / surface | `#FFFFFA` background; `#FFFFFF` content surfaces; navy on background 15.47:1. |
| Text / muted / border | `#222222`, `#5B5B68`, `#C5C5D0`; muted on white 6.69:1. Check border contrast against its adjoining surface; use a darker boundary where needed. |
| Success | `#17633B` on `#EAF6EF` (6.56:1), for Received labels and success feedback. |
| Warning | `#854600` on `#FFF4E0` (6.71:1), with warning text/icon. |
| Error | `#A12A22` on `#FFF0EE` (6.60:1), with an error message. |
| Information | `#173D70` on `#EDF5FC` (9.84:1), for neutral context. |
| Type | Open Sans: body 15px/1.5, controls and tables 14–15px, supporting text at least 14px; Cardo: page heading 24px/1.25, section heading 20px, subheading 17px. Use tabular numerals for amounts. |
| Spacing | 4, 8, 12, 16, 24, 32px scale; 16px between related sections, 24px between major sections. |
| Shape / elevation | 6px control radius, 8px panels, thin borders; optional subtle `0 1px 3px rgba(34,34,34,.08)` for menus/drawers only. Avoid decorative shadows and gradients. |
| Controls / tables | Desktop controls at least 40px high; touch targets at least 44 × 44 CSS px, including icon buttons. Table rows target 44px, with 8–12px cell padding and right-aligned amounts. |
| Focus | 2px solid navy outline with 2px offset on light surfaces; white on navy. Ensure at least 3:1 against adjacent colors, including orange and semantic backgrounds; add a contrasting outer ring when necessary. |
| Breakpoints | Drawer below 1024px; desktop sidebar from 1024px. Use container width, not viewport alone, to choose two columns; collapse when workspace is under 900px. |

Text and text-bearing controls require WCAG contrast of at least 4.5:1 for normal text and 3:1 for large text; meaningful control boundaries, state indicators, and focus indicators require at least 3:1 against adjacent colors. Check focus appearance and contrast under keyboard use. Disabled controls should remain legible and have an explanation where the reason is not obvious. Do not use color alone for statuses, categories, errors, or chart meaning.

### Icons

The installed [web dependencies](../apps/web/package.json) do not include an icon library, and `public/` contains framework placeholder SVGs rather than an operational icon set. First reuse existing suitable assets if any are found during implementation; otherwise propose a small, consistent locally bundled set such as Lucide, subject to owner approval for a dependency. This stage installs nothing. Decorative icons use `aria-hidden`; icon-only controls need accessible names. Prefer text plus icon for navigation and actions.

| Meaning | Suggested recognizable icon |
| --- | --- |
| Orders / receipts | receipt or clipboard-list |
| Menu / vegetable, non-vegetable, extra rice | utensils / leaf, utensils, bowl |
| Employees / visitors | users / user-round |
| Search / dates | search / calendar |
| Cash or payment / Salary Deduction | banknote or wallet / badge or payroll document |
| Refresh / add / edit / save / cancel | refresh-cw / plus / pencil / save / x |
| Pending / Received / warning / error | clock / circle-check / triangle-alert / circle-alert |
| Reports | chart-bar or file-chart |

Payment icons are labels for allocations, not evidence of payment settlement. Category icons supplement category names; avoid an unverified food symbol where it could mislead.

## Responsive layout and density

Use `min-width: 0` in grid and flex children. Center the workspace within a practical maximum width of 1440px, with 24px desktop, 16px tablet, and 12–16px mobile padding. Search inputs target 280–360px and date controls 160–200px, constrained by available width; filters wrap as a compact row. Avoid full-width inputs on large screens unless their content requires it.

| Viewport | Intended behavior |
| --- | --- |
| 1440px / 1366px | Sidebar plus a two-column workflow when workspace permits; order form on the left and payment summary on the right. Compact filters and horizontal summaries. |
| 1024px landscape | Sidebar stays visible; available workspace is about 808px before padding, so use a single workflow column with compact grouped fields and two-column subgroups only where they fit. |
| 768px portrait | Drawer navigation, compact filter rows; stack major form sections, use two small fields per row only when labels and inputs fit. |
| 390px / 375px | Drawer, one-column sections, 44px touch controls, wrapped actions and full-available-width fields where helpful. Keep totals visible without horizontal page scrolling. |

At 200% zoom and on narrow screens, text must reflow and controls must remain reachable. Put wide tables in individually scrollable, labeled, keyboard-focusable regions with visible scroll affordance, meaningful captions, row/column headers and tabular numbers. Avoid clipping important names, identifiers or amounts; allow wrapping or an accessible detail view. No page-level horizontal overflow at the target widths, except browser zoom/device behavior outside the app's control.

## Search and autocomplete

Proposed shared interaction for employee and visitor lookup and dish selection, using the existing authenticated client. Begin requests 250–300ms after the last keystroke; cancel previous requests and also ignore stale responses by request identity. Bound results, show a refine-search hint when truncated, and do not send a request for every keystroke. Preserve existing manual search as a fallback if needed. An empty query should not automatically retrieve a large catalog.

- Employee: query existing `GET /api/employees` by number or name, limit 20; show name, complete text identifier (including leading zeros), and optional position. Visitor: `GET /api/visitors` by name, limit 20; show name and stable visitor ID because names are not unique. Do not add extra personal details.
- Dishes: use existing `GET /api/dishes` search and current bounded alphabetical catalog behavior (up to 1,000 matches, fetched in pages of 100, presented 20 at a time). Inactive or already selected dishes are identifiable and cannot be selected. For the recorded menu in Pending editing, filter the already loaded saved menu locally; do not search or substitute a different menu.
- Display an associated label, selected item and explicit Clear action. Distinguish idle, loading, no matches, truncated results, and recoverable errors; announce concise changes with a polite live status. Preserve the typed query after errors and provide retry. Selecting a suggestion commits its stable identifier, not just its name.
- Use the editable ARIA combobox pattern: input `role=combobox`, `aria-expanded`, `aria-controls`, `aria-autocomplete=list`, and `aria-activedescendant` only for a rendered active option; popup `role=listbox` with uniquely identified `role=option` entries. Arrow keys move the active option without committing; Enter selects it; Escape closes without changing the committed selection; Tab closes and moves focus normally without silently selecting. Keep focus in the input. Clearly distinguish focus, active option and selected item. Position the bounded popup within the viewport, allow internal scrolling, and provide 44px touch rows.
- Do not claim fuzzy matching, server-side alphabetical ranking, or popularity ordering. Current dish results are sorted locally; the API does not provide menu-selection-frequency counts. Alphabetical fallback remains until an approved frequency contract exists; sales volume is not a substitute.

## Screen specifications

### Login and session

Center a restrained sign-in panel (maximum 400px) with ASI identity, labeled login name and password, a single primary action, and inline accessible errors. An optional labeled Show/Hide password button must preserve input focus, use `type=button`, and expose its state. Preserve generic credential failure messaging, password clearing, authenticated session handling and sign-out behavior. Show a plain session-expired message and return to sign-in on 401; do not disclose technical session details or credentials.

### Orders

Make Orders the highest-priority workflow. Show a compact date/status filter row and paged order register with customer, date, amount, status and View action. Clearly label existing Received/Pending subtotals as **this page only**; full-period totals belong in Reports. Use text plus status color. Keep actions reachable on mobile and do not truncate order identity.

For a new order, present **service date and menu → customer → items → payment → Save Pending**. Keep date lookup clear, including no assigned menu. Employee/visitor selection precedes a bounded lookup; allow visitor creation in context. Show selected offering name, category, authoritative price, quantity controls, line total and order total. On wide workspaces place items/customer to the left and a payment summary to the right; on smaller screens put payment after items. Summaries show total, allocated amount and difference in pesos, with a non-color cue when incomplete.

Offer the existing five employee payment categories and clear single/split controls; visitor orders remain Finance only. Pending allocations may be incomplete, but Received requires the existing balanced positive allocation rules. Saving creates Pending, not Received. Maintain exact integer-centavo calculations and server authority; never imply an allocation verifies GCash, cash settlement or payroll.

Pending details offer Edit for both currently supported roles. Retain the saved customer, service date, menu, and original item snapshots; allow only existing item/quantity/allocation edits. Admin-only reversal presents the existing five reasons, requires a non-whitespace explanation for Other and the checkbox using the authenticated display name, and explains that current recognized totals change. Mark Received, reversal, and re-marking use existing version checks and audit handling. On a stale version or uncertain edit, require reload and review; never silently retry with a new version. Preserve order creation's exact idempotency-key/payload retry and its explicit uncertain-outcome guidance.

### Menu

Place searchable reusable dishes and selected-dish review together on a wide workspace; stack on narrow screens. Provide compact category and active filters, a quick create-and-select form, selected count, and a review before saving. Prevent duplicate IDs and preserve the existing 100-dish limit. Show actual saved offering categories and configured prices from the server; reference prices are not editable catalog prices. Do not add reclassification, deletion, price overrides, or a menu index.

For multi-date scheduling, show chosen dates, the reviewed current menu for each date, and explicit replacement confirmations only where a different assignment exists. Submit the existing expected menu IDs; on conflict, require a fresh review. Explain that future assignments do not rewrite historical order menu, item or price snapshots. Existing inspection by menu ID or date remains available.

### Employees and visitors

Employees: place a bounded name/number search and pagination above a readable directory; preserve complete text identifiers. Separate the Admin-only CSV import panel from routine search. Explain accepted `.csv` and 8 MiB limit, display safe outcome counts and record/field error codes without raw rows or contacts, and explain an uncertain result before a deliberate retry. Assistant Admin cannot import; backend checks remain authoritative. No import-history listing is currently exposed.

Visitors: within order entry, search first and show distinct IDs even for matching names; offer creation of a missing display name and select the returned record. Collect only existing required information. Do not imply name uniqueness or add a separate visitor module.

### Reports and financial visualization

Place period controls and View/Refresh in a compact row; modes are daily, Monday–Sunday week containing the selected day, calendar month, and inclusive custom range. Show the backend's actual inclusive start/end, current Received-only scope, loading/error/empty states, and a refresh action. All sections must use one response from `GET /api/reports/bundle`, not independent snapshots.

Use a compact summary strip for recognized sales, Received order count, meal/item quantities, and total Salary Deduction allocated. The existing [bundle type](../apps/web/src/lib/reports.ts) supplies these values, category/item rows, five payment-category totals, SD employee totals and recorded per-order details. Retain tables and snapshot labels for auditability, including recorded employee name and organizational fields. SD represents allocation, not payroll completion. Current corrections change current reports; do not imply locking or finalized-period adjustments.

Add an optional CSS/SVG horizontal bar per **Cash, GCash, Salary Deduction, Incentive, Finance**, derived from the corresponding `payments.totals` and labeled with the exact formatted amount. Distinct accessible text and the numerical payment table remain available independent of color or visual bars. Label the graphic “Payment allocations”; split orders contribute to each allocation and the graphic does not show verified payment. Do not invent time series or totals for absent API fields.

Parse decimal strings to integer centavos using the existing exact-money approach; never calculate money via JavaScript floating point. For bar lengths, compute a bounded scaled integer ratio from centavos and convert only that nonmonetary ratio for CSS; if the allocation total is zero, show zero-length bars and “No allocations” rather than dividing by zero. Do not infer missing categories as nonzero. Preserve exact displayed amounts independent of visual rounding. Avoid a chart dependency for this small comparison.

## Interaction, accessibility and performance

- Loading: use concise inline status text, prevent duplicate submissions, preserve layout and avoid indefinite spinners. Disable only affected actions and explain prerequisites. Use `role=status` for progress/success, `role=alert` for actionable errors, and link field errors with `aria-describedby` and `aria-invalid`.
- Errors: retain safe user input where possible. For a network-uncertain mutation, explain that it may have succeeded; use only the existing safe retry/review behavior. Do not automatically resubmit mutations. Preserve version conflicts, idempotency and backend permission enforcement.
- Confirmations: use existing contextual confirmations for Received reversal and menu replacement; no added approvals or payment-verification steps. Keep Cancel and Save distinct and keyboard reachable.
- Use semantic headings, labels, buttons, fieldsets, tables and landmarks; visible focus, predictable tab order and no keyboard traps except a properly managed open modal. Announce state changes without repeated noisy messages. Test with keyboard and a screen reader; respect reduced motion and avoid decorative animation.
- Reuse existing CSS, API client and small shared controls where doing so removes real duplication. Do not cache sensitive employee data or credentials in browser storage. Limit search results and debounce requests; abort stale reads. Keep the complete report bundle's existing behavior visible as a scalability limitation rather than inventing pagination.
- Acceptance targets: at 1440, 1366, 1024, 768, 390 and 375 CSS px, no unintended page overflow, clipped actions or inaccessible labels; table regions scroll by keyboard. Within one 300ms debounce window issue no more than one search for the final unchanged query, and stale results never replace newer ones. Show immediate loading feedback; network latency is not a guaranteed UI response time. No new heavyweight animation or chart dependency by default.

## Implementation roadmap

Each phase is a later change requiring review; preserve backend contracts and current business behavior throughout.

| Phase | Likely files and scope | Dependencies, acceptance and regression risks |
| --- | --- | --- |
| 1. Shell and tokens | `meal-app.tsx`, `globals.css`: sidebar/drawer, common controls and responsive tokens. | Verify four destinations, focus management, sign-out, session expiry, 375–1440px reflow, and preservation of unsaved/uncertain order handling. Any new icon dependency requires approval. |
| 2. Orders and autocomplete | `order-entry.tsx`, `customer-picker.tsx`, `order-register.tsx`, `pending-order-editor.tsx`, existing shared client/styles. | Test keyboard/ARIA and stale searches, quantities, exact split totals, visitor Finance, Pending editing, idempotent retry, Received and Admin reversal/version conflicts on desktop and mobile. Server-side popularity is unavailable. |
| 3. Menu, Employees, Visitors | `dish-catalog.tsx`, `menu-workspace.tsx`, `menu-scheduling.tsx`, `employee-directory.tsx`, customer picker. | Test bounded search and alphabetical fallback, multi-date replacement conflicts and historical provenance, CSV authorization/privacy/errors, visitor identities and mobile tables. No new endpoint or standalone visitor directory. |
| 4. Reports | `reports-workspace.tsx`, `lib/reports.ts`, shared styles. | Compare all five bar labels/values, KPIs and tables with the same bundle for all periods, zero data, split allocations and status corrections. Test exact cents and zero denominator; do not add inferred data. |
| 5. Login and final review | `meal-app.tsx`, shared styles and relevant existing tests. | Validate labels, optional password toggle, focus, screen-reader feedback, session expiry, mobile/desktop layouts and contrast. Run lint, frontend tests, TypeScript and production build; run applicable integration tests if API behavior changes. |

Every phase should include focused automated regression tests for changed behavior and real-browser checks with synthetic data. Record viewports, roles, evidence, and any unverified scenarios. Do not treat code inspection as browser verification.

## Capability gaps and decisions

- The current dish API does not expose menu-selection-frequency ranking; sorting is local and bounded. Its ranking definition, tie rules and any supporting API require a separate decision. Employee and visitor search support existing text queries, not an assumed fuzzy-search service.
- There is no menu-definition index, assigned-date directory, import-history listing endpoint, or report pagination; do not design controls that depend on them. Report bundles contain no time series; visualize only fields actually returned.
- The [business requirements](business-requirements.md) describe both roles correcting Received, whereas the current frontend and documented implementation allow reversal only for Admin. This specification preserves the implemented Admin-only behavior; the owner should resolve the documentation/policy discrepancy separately before changing permissions.
- A Lucide or other icon dependency is optional and requires approval if existing assets are unsuitable. Owner review of this specification and of the proposed reporting presentation is needed before implementation; no new financial or privacy policy is decided here.
