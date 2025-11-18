# Tailwind CSS Setup

This project uses Tailwind CSS locally instead of the CDN version.

## Files

- `package.json` - npm configuration with Tailwind CSS dependency
- `tailwind.config.js` - Tailwind configuration that scans templates and static JS files
- `input.css` - Source file with Tailwind directives
- `static/tailwind.css` - Generated minified CSS file (33KB)

## Rebuilding Tailwind CSS

If you make changes to templates or need to rebuild the CSS:

```bash
# Install dependencies (first time only)
npm install

# Build the CSS
npm run build:css
```

This will regenerate `static/tailwind.css` with only the classes used in your templates and JavaScript files.

## What Changed

**Before:**
```html
<script src="https://cdn.tailwindcss.com"></script>
```

**After:**
```html
<link rel="stylesheet" href="{{ url_for('static', filename='tailwind.css') }}">
```

## Benefits

- ✅ No internet connection required
- ✅ Faster page loads (smaller file size - 33KB vs CDN overhead)
- ✅ Only includes classes actually used in the project
- ✅ Works offline

## Logo Visibility

The logo is always visible in `templates/base.html` (lines 499-500) without any authentication checks, ensuring it displays for all users.
