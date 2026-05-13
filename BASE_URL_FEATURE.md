# Base URL Feature Implementation Summary

## Overview
This feature adds the ability for users to specify and manage the base URL of the application being tested. Test steps with a `path` element are now rendered as clickable links that combine the base URL with the path.

## Implementation Details

### 1. Configuration Support (`testbook/config.py`)
- Added `default_base_url` field to source repo configuration
- Default value: `http://localhost:5004/`
- Configured in `config.yml` under `source_repo` section
- Updated `config.yml.example` with documentation of the new field

### 2. Backend Changes (`testbook/web.py`)
- Added `default_base_url` to the configuration returned to templates
- Added new API endpoint `/api/default-base-url` that returns the configured default URL
- Passes `default_base_url` to index template on all routes

### 3. Frontend UI (`testbook/templates/index.html`)
- Added Base URL control section under branch selector in header
- Contains:
  - Text input field for entering/editing the base URL
  - "Save" button to persist the URL
  - "Reset to Default" button to clear stored URL and revert to configured default
- Added hidden script element with the configured default base URL as JSON

### 4. JavaScript Functionality
- **URL Storage**: Uses browser's `localStorage` with key `testbook_base_url`
- **URL Management**: 
  - `getCurrentBaseUrl()` - returns stored URL or configured default
  - `getStoredBaseUrl()` - returns raw localStorage value
  - `setStoredBaseUrl()` - persists URL to localStorage
- **URL Input**: 
  - Initialized with current URL on page load
  - Save button saves new URL to localStorage
  - Reset button clears localStorage entry
  - Enter key triggers save
- **Path Rendering**: 
  - When rendering test steps, paths are now rendered as clickable links
  - Full URL is created by: `baseUrl + "/" + path` (with proper slash handling)
  - Links open in new tab with `target="_blank"` 
- **Refresh on Change**: When URL is saved or reset, the current test view is refreshed to update all path links

### 5. Styling (`testbook/static/style.css`)
- Added styles for base URL controls:
  - `.app-base-url-controls` - container section
  - `.base-url-form` - form layout with flexbox
  - `.base-url-label` - label styling
  - `.base-url-input` - input field styling with focus states
  - `.btn-base-url` - primary save button
  - `.btn-base-url-reset` - secondary reset button
- Enhanced `.step-link` styling for clickable links

## User Workflow

### Using the Feature
1. **Default Behavior**: On first load, the Base URL input is populated with the configured default (`http://localhost:5004/`)
2. **Changing the URL**:
   - Enter a new URL in the "Base URL" input field
   - Click "Save" button (or press Enter)
   - The new URL is persisted in browser localStorage
   - Current view is refreshed with updated links
3. **Resetting to Default**:
   - Click "Reset to Default" button
   - localStorage entry is cleared
   - Input returns to configured default
   - Current view is refreshed with updated links
4. **Persistence**: 
   - Saved URL persists across page refreshes
   - Across all branches (global to the browser)
   - Clearing browser localStorage will reset it

### Step Path Rendering
- Steps with a `path` field now display as clickable links
- Example: If base URL is `http://example.com` and path is `/dashboard`, link goes to `http://example.com/dashboard`
- Links open in new browser tabs

## Configuration Example

### config.yml
```yaml
source_repo:
  repo_name: "DOAJ/doaj"
  tests_path: "doajtest/testbook"
  default_branch: "develop"
  resources_path: "doajtest"
  default_base_url: "http://localhost:5004/"
  github_token: "your_token_here"
```

### Environment Variable Override
The default base URL can also be configured via an environment variable (if needed in future):
```bash
TESTBOOK_DEFAULT_BASE_URL=http://production.example.com/
```

## Technical Notes

### Storage Strategy
- Uses browser's `localStorage` for client-side persistence
- Key: `testbook_base_url`
- Site-wide scope (applies to all test suites and branches)
- Survives page refreshes and browser restarts

### URL Construction
- Base URL and path are combined with careful slash handling
- Example: `baseUrl.replace(/\/$/, '') + '/' + path.replace(/^\//, '')`
- Prevents double slashes or missing slashes

### Rendering
- Paths are rendered as `<a>` tags with:
  - `target="_blank"` to open in new tab
  - `rel="noopener noreferrer"` for security
  - HTML-escaped content

## Testing
- All 48 existing tests pass
- Feature tested with:
  - API endpoint returns correct default
  - HTML includes all necessary elements
  - localStorage key name is correct
  - JavaScript functions properly

## Future Enhancements
Possible future improvements:
- Per-branch base URL configuration
- URL history/dropdown of recent URLs
- Automatic URL validation
- Save URL to backend for per-user preferences

