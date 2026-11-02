# SaneQueue UI development workbench

Isolated HTML/Vite/Storybook tooling. It is **not** an alternative PBX frontend and never imports AMI, database, audio or live account fixtures. Production Python requirements and PBX installation stay independent.

## Development

Use Node 24 and run from the repository root:

```powershell
npm ci --prefix tools/ui-workbench
npm run dev --prefix tools/ui-workbench
# Separate terminal, optional:
npm run storybook --prefix tools/ui-workbench
```

Workbench: http://127.0.0.1:18910 · Storybook: http://127.0.0.1:18911. Both bind loopback only. Ports are strict, so an unrelated service is never reused silently.

## Browser tests

```powershell
# Optional: choose a writable local cache; use the SAME value for install and test.
$env:PLAYWRIGHT_BROWSERS_PATH='C:/path/to/writable/playwright-browsers'
node tools/ui-workbench/node_modules/@playwright/test/cli.js install chromium --only-shell
npm run build-storybook --prefix tools/ui-workbench
npm test --prefix tools/ui-workbench
```

For this existing workspace the installed browser cache is `../playwright-browsers` relative to the repository. Browser binaries and node_modules are excluded from source control. A clean clone needs `npm ci` and browser installation. CI may require `install --with-deps chromium --only-shell`.

The eight Windows screenshots cover FA/EN, light/dark, 390/1280 widths. First review captures visually, then use `npm run test:update --prefix tools/ui-workbench` for an intentional baseline change. A passing comparison to newly generated screenshots is regression evidence, not independent design approval. CI on Linux runs functional/axe tests with `UI_SKIP_VISUAL=1` and saves fresh screenshots as artifacts; Linux visual approval needs separately reviewed Linux baselines. Tests abort non-local browser HTTP requests. Storybook's own dev manager may attempt optional update/services requests; telemetry is disabled and it contains only synthetic data.

## Shared design contract

- `src/tokens.json`: canonical v1 color/spacing/radius values; `npm run tokens --prefix tools/ui-workbench` regenerates CSS. Source-aligned palettes with stronger contrast for muted/status text.
- `src/components.js`: semantic vanilla DOM, no framework rewrite. Four families: Button, KPI, AgentStatus, DataTable; state panels and a validation form exercise interaction.
- `src/*.stories.js`: editable component and composed-state examples.
- `design-manifest.json`: Figma node IDs and explicit font limitation. Figma updates are currently reviewed/manual; there is no automatic bidirectional synchronization or Code Connect mapping.
- Existing local Vazirmatn font is reused. Only that font directory is permitted outside the workbench Vite root. No external font CDN.

Do not install these dependencies on a call server or ship `storybook-static` as the operational application. This setup does not replace live telephony, app permission, load, or deployment acceptance tests. Integrating the foundations into production screens is a separate approved change.

## آموزش فارسی

### Reporting charts and Persian calendar

Open `/?view=report-design&locale=fa&theme=dark` (also `en` / `light`). This synthetic fixture imports the actual shared product chart/calendar scripts. The `SaneQueue/Reporting` Storybook story uses the same modules. Fourteen reporting tests cover 8 locale/theme/width combinations, page and calendar screenshots, axe, keyboard/focus, ISO dates, leap-day/month navigation, range validation, chart paging, resize and real PNG/SVG downloads. Baselines are Windows-specific; Linux CI captures fresh artifacts without claiming a Windows pixel comparison. The fixture is not a deployed operational page or proof of every chart integration.

از نوار بالای نمونه، زبان، تم، صف و حالت نمایش را انتخاب کنید. راهنمای هر شاخص با «راهنمای شاخص» باز می‌شود. «نامشخص» یعنی شواهد کافی نداریم، نه مقدار صفر. جدول در موبایل پیمایش افقی دارد. حالت‌های بارگذاری، خالی، خطا، نبود مجوز و غیرفعال از همان نوار قابل مشاهده‌اند. فرم پروفایل صرفاً اعتبارسنجی نمایشی دارد و چیزی روی سرور ذخیره نمی‌کند. داده‌های این کارگاه ساختگی هستند.
