# ASI Meal Management — Premium Enterprise UI Design

**Stage 14G.1 — UI/UX assessment and specification**
**Status:** Premium Enterprise is the approved visual direction; token details are proposed for review. Implementation is not authorized by this document.
**Scope:** Documentation only. This specification does not change application behavior, permissions, business rules, or services.

## Purpose and evidence

The recommended visual direction is **Premium Enterprise**: a more deliberate information hierarchy, compact and precise geometry, layered but readable surfaces, consistent icon treatment, and carefully finished interactions. It should feel more considered than a collection of generic panels without becoming a decorative dashboard.

This assessment is based on the current source and documented requirements in the [existing UI specification](ui-ux-design-spec.md), [business requirements](business-requirements.md), and [Super Admin audit design](super-admin-audit-design.md). The relevant implementation includes [global styles](../apps/web/src/app/globals.css), [application navigation](../apps/web/src/components/app-navigation.tsx), [Activity Logs](../apps/web/src/components/activity-workspace.tsx), [Users](../apps/web/src/components/users-workspace.tsx), [Orders](../apps/web/src/components/order-entry.tsx), [order register](../apps/web/src/components/order-register.tsx), [Menu](../apps/web/src/components/menu-workspace.tsx), [Customers](../apps/web/src/components/customers-workspace.tsx), [customer picker](../apps/web/src/components/customer-picker.tsx), [Reports](../apps/web/src/components/reports-workspace.tsx), and [application shell and authentication screens](../apps/web/src/components/meal-app.tsx).

No rendered page or screenshot was available for this assessment. All findings below are therefore **code-based observations**, not claims about rendered appearance. Visual balance, clipping, perceived density, and actual contrast on-screen must be confirmed in a browser before or during implementation.

## 1. Current interface audit

The current product has six destinations: Orders, Menu, Customers, Reports, Users, and Activity Logs. Users and Activity Logs are only included in navigation for Super Admin. The desktop sidebar is 216px wide from 1024px upward; below 1024px a labeled Menu button opens a 288px/85vw native modal drawer. The shell already includes a skip link, current-page navigation semantics, focus return, and a destination-heading focus step.

Cardo and Open Sans are already imported from local Fontsource packages. Navigation and Activity Logs use locally authored inline SVGs; the package manifest does not include a dedicated icon library. Global CSS currently defines the ASI brand colors, several semantic colors, a 6px common control radius, 8px panels, visible keyboard focus, and responsive rules including a mobile breakpoint at 600px. Orders and daily-menu layouts also use container queries.

| Finding | Classification | Severity | Confirmed source observation and design response |
|---|---|---:|---|
| Activity events are each rendered as a `.panel` with a repeated border, radius, and padding. Actor/time and target are separate paragraphs; details expand in-place. | Structural UX; visual hierarchy | Medium | The current implementation is readable and newest-first, but repeated panel treatment makes the audit history visually uniform. Recompose it as a compact, timeline-inspired audit ledger with a clear action line, aligned actor/target/time metadata, restrained separators, and a clearly grouped disclosure area. |
| Activity filters place six controls and Apply filters in one wrapping panel. | Structural UX; responsive | Medium | The supported controls are date range, numeric actor ID, action, entity, and reference. Keep every filter and explicit submit behavior, but group related controls and establish a predictable desktop grid that wraps intentionally on narrow screens. Do not add export or broader search. |
| Users presents a five-column account table, text role/status values, a Search form, Previous/Next, an inline edit form, and a collapsed Create account disclosure. Account edits use a browser confirmation. | Structural UX; visual hierarchy | Medium | Keep the directory compact and scannable; strengthen the role/status/action column hierarchy and the separation of creation from search. Make existing role, status, and temporary-password changes explicit and consequential without adding account capabilities or a different permission model. |
| Most buttons inherit the same filled navy treatment. Secondary, text, icon, and orange-accent variants exist, but their use is class-based and not described as a component system. | Component consistency | Medium | Specify clear primary, secondary, quiet, and destructive roles. Use filled navy only for the main action in a local workflow; keep secondary and quiet actions visually lighter. Reserve destructive styling for existing risky actions such as disabling an account, with an explicit text label. |
| Brand and semantic colors are centralized, but additional colors and radii are repeated as literals across the stylesheet; observed radii include 4px, 5px, 6px, 7px, and 8px. | Component consistency; decorative-only opportunity | Low | Consolidate visual decisions into a small token set during implementation. Preserve existing brand colors and semantic meaning; avoid a wholesale CSS rewrite. |
| Page, section, and subheading sizes and fonts have a baseline, but the current code does not define a broader type or spacing scale. | Visual hierarchy | Low | Retain Cardo for headings and Open Sans for body and controls. Give page headings, supporting text, section titles, labels, metadata, and amounts deliberate, consistent roles. |
| Global table rows use 14px text and 12px vertical cell padding; many data tables rely on a keyboard-focusable horizontal scroll region. Dish Catalog alone has a custom narrow-screen card-like row treatment. | Responsive; structural UX | Medium | Keep accurate tables and numeric alignment for operational and financial records. At narrow widths, use intentional row summaries only where all labels and values remain clear; otherwise retain an accessible, keyboard-scrollable table region rather than squeezing columns. |
| Keyboard focus styles, semantic form labels, live status/error messages, a skip link, and a native modal navigation drawer are present. No reduced-motion override is defined in the inspected global stylesheet. | Accessibility | Low | Preserve existing affordances and test them in a browser. The design system should include reduced-motion behavior for any newly introduced motion; do not add motion for decoration alone. |
| The stylesheet includes responsive rules at 600px and 1024px plus container-query layouts, but screenshots at the requested viewports are unavailable. | Responsive; visual assumption requiring capture | Unverified | Do not call the existing layout broken based on source alone. Verify 1024px and 768px carefully because the navigation changes at 1024px while content-specific adaptations are limited. |

The existing strengths are meaningful: a consistent brand palette and local fonts, labeled navigation icons, accessible table regions, explicit loading/error/empty messages in key workspaces, exact business-oriented data, and a Super Admin-only audit UI. The redesign should refine these foundations rather than replace their behavior.

## 2. Design principles and approved direction

1. Make high-frequency operational actions easy to locate and complete.
2. Use information hierarchy, alignment, spacing, and typography before decoration.
3. Use restrained depth: subtle borders and low elevation for floating elements, not a shadow or glass effect on every surface.
4. Keep financial tables, employee details, account forms, and audit payload summaries opaque and high contrast.
5. Preserve the existing information architecture, API contracts, backend authorization, privacy projection, and business workflows.
6. Keep the interface local and self-contained. Reuse the existing React/CSS structure, inline SVG approach, and locally bundled fonts; add no design framework, icon dependency, external asset, or cloud dependency.
7. Treat all event and account information as operational data, not feed content. No social-feed styling, celebratory motion, or decorative charting.

### Brand palette

| Token | Value | Role |
|---|---|---|
| ASI navy | `#160D76` | Primary action, headings, active navigation, and strong emphasis. |
| ASI blue | `#4094D9` | Secondary accent, informational emphasis, and selected-state details; do not use white text on this blue for normal-size text. |
| ASI orange | `#F08530` | Sparse brand accent and attention marker; pair with dark text, not white. |
| Warm background | `#FFFFFA` | Main application canvas. |
| Primary text | `#222222` | Body text, labels, and dark text on orange. |
| Muted text | `#5B5B68` | Supporting information that remains readable. |

### Proposed design tokens

These are CSS implementation targets, not current measured values. The existing semantic colors should be retained and normalized into the token roles below.

| Role | Proposed token/value | Use |
|---|---|---|
| Surfaces | `--surface: #FFFFFF`; `--surface-subtle: #F4F4F9`; `--surface-info: #EDF5FC` | Opaque content, quiet inset areas, and informational selection. |
| Borders | `--border: #C5C5D0`; `--border-subtle: #E3E3EC`; `--border-strong: #AAAAB8` | Default division, low-priority separators, and form boundaries. Check the actual adjacent-color contrast for control boundaries. |
| Semantic states | Existing success `#17633B` / `#EAF6EF`; warning `#854600` / `#FFF4E0`; error `#A12A22` / `#FFF0EE`; info `#173D70` / `#EDF5FC` | Text/icon and supporting surface pairs. Always pair color with a label or other textual cue. |
| Type | Open Sans: body 15px/1.5; control/table 14–15px; supporting copy at least 13px. Cardo: page title 28px/1.2; section title 20px/1.3; minor title 17px/1.35. | Strong but compact hierarchy. Use tabular numerals for quantities, IDs, and currency. Keep dense audit metadata readable. |
| Spacing | 4, 8, 12, 16, 24, 32px | Tight label/control grouping through major-section separation. Use 16px between related elements and 24px between major page sections. |
| Shape | 4px compact controls/chips; 6px standard controls; 8px panels; optional 12px only for a feature-level container | Intentional variation without oversized rounding. Keep tables and their cells square. |
| Elevation | `--shadow-popover: 0 4px 14px rgb(22 13 118 / 0.12)`; `--shadow-dialog: 0 12px 32px rgb(34 34 34 / 0.18)` | Popovers and dialogs only. Default panels use border and surface contrast rather than shadow. |
| Control size | 40px minimum desktop height; 44px minimum touch target | Buttons, fields, selects, and icon buttons. Ensure the clickable area, not just the glyph, meets the target. |
| Table density | 44px target row; 8–12px vertical and horizontal cell padding | Dense enough for registers without making values hard to scan. Preserve adequate row height for mobile and keyboard focus. |
| Focus | 2px visible outline with 2px offset; use a contrasting ring where the adjacent surface is navy, orange, or semantic-tinted | Keyboard focus must remain distinct from hover, active, and selected states. |
| Motion | 120–180ms for state changes where movement adds orientation; no parallax or entrance choreography | Honor `prefers-reduced-motion: reduce` by removing nonessential transitions. Do not animate table rows or audit history on load. |
| Layout | 216px desktop sidebar; workspace maximum width 1440px; gutters 24px desktop, 16px tablet, 12–16px mobile | Keep the current shell concept; use container width to choose content columns. |

Normal-size text must meet WCAG AA contrast of at least 4.5:1; large text and meaningful graphical/control boundaries must meet at least 3:1 against adjoining colors. Recheck the final rendered combinations, especially focus rings, disabled controls, orange accents, and semantic badges. Existing documented contrast calculations for brand/semantic pairs are a starting point, not a substitute for checking actual components.

### Action hierarchy

- **Primary:** One visually dominant, filled navy action per local task group, such as Save Pending or Apply filters.
- **Secondary:** Navy text with a light or transparent surface and a clear boundary; use for cancel, back, refresh, and other non-primary actions.
- **Quiet:** Text action or low-emphasis control for reversible navigation and secondary disclosure. Give it a visible hover and focus state.
- **Destructive / consequential:** Reserved red treatment and an explicit verb phrase for existing actions that disable an account or deactivate/delete a catalog item. Keep a distinct confirmation step where the current workflow requires it. Do not use destructive styling for ordinary “Edit”, “View”, or “Cancel”.

Do not render every button as a filled navy pill. Keep corners modest and consistent; do not use pill geometry for large form actions.

## 3. Shared component specifications

### Page header and work areas

- Use a consistent page header with a 28px Cardo heading, one short supporting sentence in muted Open Sans, and any existing primary page action aligned at the end of the header row.
- At widths where header contents cannot fit comfortably, wrap the action below the heading; never shrink the title until it is unreadable.
- Use white opaque work surfaces with a thin boundary. Use a subtle inset tint to distinguish filter controls, totals, or contextual information; avoid nesting a stack of indistinguishable cards.
- Establish clear grouping with whitespace and a small section title. Avoid explanatory paragraphs that restate the labels or workflow.

### Buttons, icons, and fields

- Use the local 20px inline SVG style already used by navigation and Activity Logs. Keep stroke weight and optical size consistent. Do not introduce an icon package in this stage.
- Pair icons with visible text for navigation and task actions. For icon-only controls, provide a concise accessible name and a 44px target.
- Fields have a persistent label, 40px desktop/44px touch minimum, clear boundary, and visible focus. Keep validation adjacent to the field and associated programmatically.
- Apply consistent hover, pressed, disabled, and focus treatments. Disabled text remains legible, with the reason stated when it is not self-evident.
- Popovers may use a subtle elevated surface with an opaque warm-white background. Do not use transparency behind text.

### Tables, status, and totals

- Keep data tables semantic, with header scope, captions where helpful, keyboard-scrollable regions when they overflow, and right-aligned tabular numerals for money and counts.
- Show Pending, Received, Active, and Disabled as text labels; a restrained badge may supplement the words but may not replace them.
- Use stable column alignment and concise labels. On mobile, prioritize record identity and action. Do not truncate identifiers, account names, dates, or monetary values; allow wrapping or an inner scroll region.
- Preserve existing order-page totals as page-scoped and Reports as the reporting-period summary. Preserve “allocation is not settlement/payroll completion” language wherever it currently appears.

### Dialogs, disclosure, and feedback

- The mobile navigation remains a modal dialog with focus containment, Escape handling, a labeled close action, background scroll lock, and focus restoration.
- Use native disclosure for existing progressive content such as visitor creation and account creation unless an established component pattern is approved. Style the disclosure marker, focus, and expanded content intentionally.
- Loading, success, empty, and error states retain their current semantic roles (`status` or `alert`) and should reserve enough space to avoid disruptive layout shifts.
- Confirmation language names the exact current action and its consequence. Do not add a confirmation or approval step to routine actions unless needed for an existing consequential operation.

## 4. Activity Logs reference design

Activity Logs is the reference screen for Stage 14G.2. It is a read-only Super Admin workspace, not a generic social activity feed.

### Page composition

1. **Compact header:** “Activity Logs”, followed by the current context: recorded events only, dates in Philippine time, and the warning that some historical actions were not logged. Keep the note visible but secondary.
2. **Filter surface:** Keep all current controls and explicit Apply filters behavior: From, To, Actor user ID, Action, Entity, Reference. At desktop, align the date pair, actor, and remaining selectors in a clear grid; place Apply filters at the end of the row. At tablet/mobile, wrap into two columns where space allows, then one column. Do not introduce filter presets, export, saved searches, or an unrestricted text query.
3. **Results ledger:** Present newest-first events as a compact, timeline-inspired ledger. Use a narrow, quiet timeline rail only as an alignment cue; avoid large colored icons, individual oversized cards, or decorative “feed” cards. Separate entries with subtle rules.
4. **Event summary:** Align a small purpose-specific inline SVG, plain-language action label, target entity/reference when the safe projection provides one, actor’s current display name and ID, and timestamp. Keep the action and target visually primary; metadata is secondary. Use explicit `Asia/Manila`/PHT time context as the current UI does.
5. **Details:** Keep the existing “View details” disclosure. When opened, show the event ID, any existing self-attested local-operator attribution with that qualification, correction reason when provided, and safe Before/After values in a compact two-column definition list on wide screens and a single column on narrow screens. Continue to humanize field labels. Do not invent missing values or render a raw payload.
6. **Pagination:** Retain Previous/Next cursor navigation and the page indicator. Keep controls close to the end of the results and keyboard reachable.

### Supported behavior and privacy constraints

- Preserve date-range, actor ID, action, entity, and reference filters; current form validation requires end date not precede start date and an entity when a reference is supplied.
- The API orders by occurrence time and event ID, uses bounded cursor pagination, interprets date bounds in `Asia/Manila`, and returns a deliberately allowlisted event projection. Keep the UI faithful to those actual values and to the note about incomplete historical coverage.
- Continue displaying the actor label as the **current** display name, not a historical name snapshot. Do not present it as proof of who performed a local CLI operation.
- Show correction reason only when returned by the existing safe projection. Preserve the explicit “local operator (self-attested)” qualification where present.
- Do not show raw audit JSON, credentials, hashes, session/CSRF identifiers, employee import rows, arbitrary free-text payloads, or new disclosures of employee/customer data. Do not add export.
- Keep authorization enforced by the backend; hidden navigation is not an access control.

### States

- **Loading:** Small inline status text; avoid skeleton rows that could be mistaken for real audit records.
- **Results:** Stable row layout; make event action, target, actor, and time distinguishable without color alone.
- **Empty:** Plain-language “No activity matches these filters” status, visually quiet but distinct from loading.
- **Error:** Safe actionable alert; do not clear the selected filters or auto-retry. Do not render partial/success-shaped results after a failed request.
- **Expanded details:** Clear disclosure focus and open state; before/after labels remain visible and data stays readable against an opaque surface.
- **Unknown event:** Neutral icon and safe fallback label. Never infer a more specific action from arbitrary payload content.

## 5. Users companion design

Users is a Super Admin-only account directory. Keep the current permission boundary and the current API behavior; visual refinement must not imply additional account-management authority.

### Directory layout

- Use the same compact page header, with one sentence clarifying that accounts are individual and temporary passwords must be shared privately.
- Keep Search accounts and the existing Search action together. Place the account table below. Maintain the existing page size of 20 and Previous/Next behavior.
- Retain the existing columns: Login, Name, Role, Status, Action. Give Login and Name adequate width; keep Edit visibly aligned in the final column. On narrow viewports either wrap row content into labeled blocks or keep a keyboard-scrollable table region. Do not hide the account identity.
- Display role and status as compact, text-bearing indicators. Password-change-required status remains explicit, not color-only.
- Keep the existing Edit action for eligible non-Super-Admin accounts. No delete action, bulk actions, additional roles, or self/other Super Admin edits.

### Create and edit interactions

- Keep Create account as a clearly labeled, secondary section below or beside the directory, rather than a competing primary action. The current disclosure is appropriate if its open state and focus are styled consistently.
- Keep fields for login, display name, role (Admin or Assistant Admin), and required temporary password. On edit, retain display name, the same two-role selection, enabled status, and the optional temporary password reset field.
- Do not add a standalone reset route or promise an email handoff. A temporary password remains a secret: never echo it in a success message, account row, confirmation, log, or UI state; clear the input after submission.
- Keep the existing explicit confirmation before saving an edit because role, status, and password changes revoke sessions. The confirmation should identify the affected login and clearly summarize the actual pending changes; do not confirm ordinary search or viewing.
- Distinguish Save changes, Cancel, and the consequential status/password fields visually. Preserve stale-update errors, permission errors, and success feedback.
- Keep the existing roles, Super Admin account restrictions, first-password-change requirement, session revocation, and backend checks unchanged. Do not create accounts or alter accounts as part of a visual implementation.

## 6. Shared application design

### Navigation and shell

- Preserve the existing 216px desktop sidebar at 1024px and above and the compact mobile header plus modal navigation drawer below 1024px.
- Retain all current labels and role-based visibility: Orders, Menu, Customers, Reports for routine roles; Users and Activity Logs additionally for Super Admin.
- Use active surface plus a visible edge/marker, not color alone. Preserve the current-page semantic, accessible text labels, role and account identity, Sign out action, skip link, keyboard focus, and drawer focus return.
- The sidebar may gain subtle surface layering and refined spacing, but keep it opaque and high contrast. A restrained translucent treatment is optional only on a floating overlay where text remains fully legible; never make core navigation or dense content glassy.

### Login and mandatory password change

- Keep the centered sign-in/password-change panel, individual-account wording, visible labels, secure password input semantics, and generic credential failure messaging.
- Use the same brand, type, control, and focus tokens. Keep a single primary submit action; Sign out on the forced password-change screen remains secondary.
- Keep authentication and mandatory-change screens free from decorative imagery, external fonts, password disclosure, and unnecessary explanatory content. Clear password fields after the existing operations.

### Workspace-specific consistency

- **Orders:** Retain the register, selected-date overview, Pending/Received labels, existing filter and pagination, and existing detail/edit/receive/reverse flows. New order continues to communicate the four-step service-date/customer/items/payment allocation sequence and saves as Pending. Keep allocation state, exact totals, version conflicts, retry guidance, and permission-sensitive reversal behavior unchanged. Avoid card layers around every item.
- **Menu:** Keep the selected service date, saved-meal summary, catalog, selected-dish review, Extra Rice treatment, and existing schedule/review confirmations. Use consistent category labels and selection states; do not add inventory, price override, menu index, or new dish capabilities.
- **Customers:** Retain the Employees/Visitors tabs and their keyboard behavior. Preserve employee import authorization and safe validation feedback. Keep the bounded customer picker, distinct visitor identity, and search-before-create guidance. Do not add a standalone visitor workflow beyond the existing directory.
- **Reports:** Retain period modes, inclusive Philippine-time period context, refresh, download actions, summary counts, sales/payment tables, employee search, and Salary Deduction snapshots. Preserve the message that SD is an allocation, not payroll completion. Do not add unsupported time series, payment verification, or decorative charts.
- **Activity Logs and Users:** Use the specific reference and companion layouts described above; visibility remains Super Admin-only and backend-enforced.

## 7. Responsive and accessibility standards

No page-level horizontal overflow, clipped primary actions, hidden labels, or inaccessible table content at any required viewport. Scrollable data regions must be keyboard focusable and have an accessible name.

| Viewport | Navigation and content | Filters, tables, overlays |
|---|---|---|
| 1440px desktop | 216px sidebar; content centered with up to 1440px maximum width and 24px page gutter. Use multi-column composition only when the content container supports it. | Activity filters in one balanced row or two aligned groups. Keep account and audit metadata on one or two well-aligned lines. Dialogs/popovers remain within viewport. |
| 1366px laptop | Same sidebar and visual hierarchy; avoid stretching forms across unused width. | Keep financial and user tables readable; avoid truncation. Ensure actions do not wrap into ambiguous neighboring rows. |
| 1024px tablet landscape | Sidebar remains visible; workspace is roughly 808px before page padding. Prefer one-column workflows unless actual inner width supports a second column. | Filter rows wrap intentionally. Audit details may remain two columns only if labels and values retain useful width. |
| 768px tablet portrait | Mobile header and drawer; single-column workspace; page gutter 16px. | Filters and user actions wrap; table regions scroll internally or use labeled responsive rows. Dialogs use available width with safe margins. |
| 390px mobile | Mobile header and drawer; 12–16px page gutter; no horizontal page overflow. Keep action labels and customer/account identifiers readable. | One-column filters and forms; 44px touch targets. Popovers and suggestion lists fit the viewport; drawers remain at most 85vw/288px. |
| 375px mobile | Same deliberate mobile layout as 390px, with text wrapping rather than clipped controls. | Verify narrow table headers, dialog padding, confirmation text, numeric amounts, and action wrapping. Avoid relying on hover. |

Accessibility acceptance:

- Use semantic page headings, landmarks, table headers/captions, form labels, fieldsets, buttons, and disclosures.
- Maintain visible keyboard focus distinct from hover, selected, and error states. Check focus against actual adjacent surfaces.
- Provide accessible names for any icon-only controls; decorative SVGs are hidden from assistive technology.
- Pair state color with text or an icon and text. Do not encode status, selection, error, or chart meaning with color alone.
- Preserve keyboard scrolling of wide tables and predictable focus order. Dialogs must support Escape when appropriate, focus containment, focus restoration, and background inertness.
- Announce loading, errors, and successful actions with the existing status/alert semantics without duplicate or noisy announcements.
- Honor `prefers-reduced-motion`; keep animation short, optional, and functional.
- Test keyboard-only operation and representative screen-reader output in a browser; source inspection alone does not establish accessibility conformance.

## 8. Visual references and feasibility

No browser page or screenshot was shared, and no page was rendered during this assessment. Consequently:

- The interface audit above is grounded in source structure and styles only.
- It does not claim that a specific screen was visually reviewed or that any viewport currently overflows.
- Existing inline SVG icons and local Cardo/Open Sans fonts are sufficient to implement this direction without new assets or dependencies.
- The current CSS and React components support a progressive, workspace-by-workspace refinement; a wholesale front-end rewrite is not necessary.

For the next implementation review, capture synthetic-data screenshots of:

1. Activity Logs at 1440px, 1024px, 768px, and 390px: default results, applied filters, expanded details, empty results, and a safe error state.
2. Users at 1440px, 1024px, 768px, and 390px: directory, create disclosure open, edit form, and confirmation.
3. Orders at 1366px and 390px: register/detail and new order with balanced and incomplete allocations.
4. Menu and Customers at 1024px and 390px, including the current mobile navigation.
5. Reports at 1366px and 390px with synthetic data and an empty reporting period.

Mask account identifiers and any employee/customer information in screenshots. Use only synthetic or specifically approved redacted records. Screenshots should identify viewport dimensions and account role, without including secrets or real personal data.

## 9. Proposed implementation stages

### Stage 14G.2 — Activity Logs reference implementation

Apply the approved tokens and refined interface styling to Activity Logs plus only the shared components needed to support it. Keep scope to the activity page, shared page-header/filter/ledger primitives if they remove real duplication, relevant global tokens/styles, and focused frontend tests. Reuse existing inline SVGs, local fonts, `RequestApi`, safe projections, and cursor pagination.

Acceptance: preserve all current filters and validation, page navigation, safe detail disclosure, timestamp/timezone meaning, actor-current-name qualification, local self-attestation qualification, authorization visibility, loading/error/empty states, keyboard operation, and privacy limits. No raw JSON, export, new audit permissions, new data, dependencies, API changes, or changes to business/security logic.

### Stage 14H — Progressive workspace refinement

Apply the reviewed visual system in small, separately testable slices to Users, Orders, Menu, Customers, Reports, Login, and shared navigation. Start with shared component roles and tokens, then refine each workspace without changing its API, permissions, or business behavior. Rebuild and visually verify the local demo only after a frontend implementation is explicitly approved; preserve its database and unrelated services.

Avoid an application-wide CSS rewrite in one step. Keep each slice focused, run its existing tests and relevant lint/type/build checks, and verify responsive browser behavior using synthetic or approved redacted data.

## 10. Visual acceptance criteria

- Brand palette remains exactly `#160D76`, `#4094D9`, `#F08530`, `#FFFFFA`, and `#222222`; semantic states remain textually identifiable.
- Cardo/Open Sans remain locally bundled; no external fonts, assets, charting package, icon library, or design framework is added for this direction.
- Page title, supporting copy, primary action, section title, data, and metadata have a consistent and visible hierarchy.
- Primary, secondary, quiet, and destructive actions look distinct; ordinary buttons are not all filled navy pills.
- Borders, corners, spacing, table density, form height, and focus treatment use a coherent small token scale.
- Activity Logs reads as a professional audit ledger, not a repeated-card social feed; all current filter and cursor behavior remains intact.
- Users remains an individual-account directory with current search, page size, roles, status, edit/create interactions, confirmation, and permission restrictions.
- Financial and employee data surfaces remain opaque, legible, and free of decorative effects that reduce contrast.
- At 1440, 1366, 1024, 768, 390, and 375 CSS pixels, there is no page-level horizontal overflow, clipped action, hidden field label, or inaccessible table content.
- Keyboard focus is visible, touch targets meet 44px, dialog/disclosure behavior is understandable, status is not color-only, and reduced motion is respected.
- Tests cover existing behavior at the component boundary; actual browser screenshots confirm the target layouts. Do not report source-level checks as visual verification.

## 11. Unresolved design questions

1. Review the proposed **timeline-inspired audit ledger** versus a conventional compact table. The recommendation is the ledger: it gives action and actor hierarchy without making the history look like a social feed, while retaining a readable tabular rhythm.
2. Confirm whether the owner prefers a slightly asymmetric header/selected surface treatment or the more conservative uniform 8px panel geometry. The recommendation is restrained asymmetry only for a page-level accent or selected state, never dense tables or sensitive forms.
3. Confirm final spacing, shadow, and radius tokens from rendered screenshots. The values in this document are implementation targets; no browser evidence was available to prove the best optical balance.
4. No new business or authorization decision is required for this design stage. Any request to change role permissions, audit visibility/details, password handling, reporting meaning, or transaction behavior is outside scope and requires separate owner review.

## 12. Verification record

- Reviewed the existing UI design, business requirements, audit design, and local-demo documentation.
- Inspected the relevant shell, Activity Logs, Users, Orders, Menu, Customers, Reports, navigation, and global-style source.
- Confirmed that Git already contains unrelated staged/unstaged work, including changes to frontend styles and components. Those files were read as the current source and were not modified by this documentation task.
- No browser screenshot or rendered page was available; visual appearance remains to be checked in the next stage.
- Documentation-only scope: no frontend build or test run is necessary. Run `git diff --check` for this document before review.
- No components, CSS, icons, fonts, assets, application logic, database, account, or service were changed.
