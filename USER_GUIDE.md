# Execution Test Panel - Quick Start Guide

## What's New?

The execution page now features an interactive test panel that lets you track test results in real-time with automatic saving.

## How to Use

### 1. Viewing a Test
Navigate to **Executions** and select an execution. After selecting a testset, you'll see all tests laid out with:
- **Test title** at the top
- **Context and Setup** information in a highlighted blue section
- **Steps** with instructions and links
- **Expected Results** for each step

### 2. Marking Results as Pass/Fail

For each expected result, you'll see two buttons:
- **✓ (Pass button)** - Click to mark as passed (turns green)
- **✗ (Fail button)** - Click to mark as failed (turns red)

When you mark a result as **Fail**:
- The button turns red
- A comment box automatically opens for that result
- The test's Pass button becomes disabled

### 3. Adding Comments

#### Result Comments
Click the **💬 (Comment button)** next to any result to toggle its comment field. Add notes explaining why a result passed or failed.

#### Step Comments
Click the **Step Comment** toggle button to collapse/expand step-level comments. Use this for notes about the step itself.

#### Test Comments
At the bottom of each test is a **Test Comment** field that's always visible. Use this for overall test feedback.

### 4. Test-Wide Pass/Fail

At the bottom of each test, you'll see the **Test Result** section with two buttons:
- **Pass**: Mark the entire test as passing
- **Fail**: Mark the entire test as failing

**Important Rules:**
- If ANY result is marked as Fail, the Pass button becomes disabled
- If ANY result is marked as Fail, the Fail button automatically highlights
- If all results are Pending, you can choose either Pass or Fail
- You can always add comments regardless of status

### 5. Automatic Saving

Everything you do is saved automatically:
- ✓ No "Save" button needed
- ✓ No page refresh required
- ✓ All data persists even after closing the page
- ✓ Other users see your updates when they refresh

## Color Guide

- **Green (#dcfce7)**: Pass status
- **Red (#fee2e2)**: Fail status
- **Blue (#e8f0ff)**: Context and Setup information
- **Yellow (#fffbf0)**: Test-wide comments

## Keyboard Shortcuts

- **Tab**: Move between form fields
- **Enter**: Submit comments (when focused)

## Tips

1. **Mark results as you test**: Don't wait until the end; mark each result immediately
2. **Add comments for failures**: Explain what went wrong so others understand the issue
3. **Use context information**: The highlighted Context and Setup sections help you understand test requirements
4. **Check test-wide buttons**: The automatic Pass/Fail logic helps prevent mistakes

## What Happens If...

### Results don't save?
- Check your browser console (F12) for errors
- Verify you have an internet connection
- Try refreshing the page to see if changes were saved

### I navigate away without saving?
- Don't worry! All changes auto-save as you make them
- You can safely navigate or close the page

### I want to undo a change?
- Click the button again to toggle back to previous state
- Or refresh to reload from database

### Multiple people are testing?
- Each person works independently
- There's no conflict resolution - last save wins
- Check comments to see who reported what

## Screen Layout

```
┌─────────────────────────────────────────────────┐
│  Suite Name: TestSet Name        [3 tests]     │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  1. Test Title                                  │
├─────────────────────────────────────────────────┤
│  Context                                        │
│  • key: value                                   │
├─────────────────────────────────────────────────┤
│  Setup                                          │
│  • Setup step 1                                 │
│  • Setup step 2                                 │
├─────────────────────────────────────────────────┤
│  Step 1: Click login button                     │
│  Path: /login                                   │
│  Expected Results:                              │
│  ┌──────────────────────────┬──────────────────┐
│  │ Page loads successfully  │ ✓ ✗ 💬           │
│  │ No errors appear         │ ✓ ✗ 💬 (pass)    │
│  └──────────────────────────┴──────────────────┘
│  Step Comment: ▶ Step Comment                   │
├─────────────────────────────────────────────────┤
│  Test Result:                                   │
│  [ Pass ]  [ Fail ]                             │
│                                                 │
│  Test Comment:                                  │
│  [________________________________]             │
│  [________________________________]             │
└─────────────────────────────────────────────────┘
```

## Troubleshooting

### Issue: Comment boxes not opening
- Try clicking the comment button again
- Refresh the page
- Check browser console for JavaScript errors

### Issue: Pass/Fail buttons not highlighting
- Make sure you're using a modern browser
- Clear cache and refresh
- Try a different browser

### Issue: Changes not saving
- Check internet connection
- Look for error messages in browser console (F12)
- Try the action again after a few seconds

## Support

For bugs or questions:
1. Check the browser console (F12) for error messages
2. Note any error messages
3. Report with the error message and steps to reproduce

## Performance Notes

- First load may take a few seconds to render all tests
- Each save takes 10-50ms (you usually won't notice)
- Page remains responsive during saves
- No full-page reloads occur

## Browser Compatibility

Works best in:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Does NOT work in:
- Internet Explorer

## More Information

For API documentation, see `API_REFERENCE.md`
For implementation details, see `EXECUTION_PANEL_IMPLEMENTATION.md`

