#!/usr/bin/env python3
"""
Validation Script for Logo/Favicon/Email/Dark Mode Updates
Verifies all changes are correctly implemented
"""

import os
import re
import sys
from pathlib import Path

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓{Colors.END} {text}")

def print_error(text):
    print(f"{Colors.RED}✗{Colors.END} {text}")

def print_info(text):
    print(f"{Colors.YELLOW}ℹ{Colors.END} {text}")

def check_file_exists(filepath):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print_success(f"File exists: {filepath}")
        return True
    else:
        print_error(f"File missing: {filepath}")
        return False

def check_icons_directory():
    """Verify icons directory and files"""
    print_header("1. Icons Directory Check")
    
    icons_dir = "icons"
    required_files = [
        "favicon.ico",
        "favicon.svg",
        "favicon-96x96.png",
        "apple-touch-icon.png",
        "scanmydata_logo_3000w.png",
        "scanmydata_logo_dark_3000w.png",
        "site.webmanifest",
        "web-app-manifest-192x192.png",
        "web-app-manifest-512x512.png",
    ]
    
    passed = True
    
    if not os.path.exists(icons_dir):
        print_error(f"Icons directory not found: {icons_dir}")
        return False
    
    print_success(f"Icons directory exists: {icons_dir}")
    
    for file in required_files:
        filepath = os.path.join(icons_dir, file)
        if not check_file_exists(filepath):
            passed = False
    
    return passed

def check_icons_route():
    """Verify icons route in app.py"""
    print_header("2. Icons Route Implementation")
    
    app_file = "app.py"
    
    if not os.path.exists(app_file):
        print_error(f"File not found: {app_file}")
        return False
    
    with open(app_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = {
        'Route decorator': r'@app\.route\(.*icons.*filename',
        'Function definition': r'def serve_icons\(filename\):',
        'send_file usage': r'send_file',
        'icons directory': r'icons_dir.*icons',
    }
    
    passed = True
    for check_name, pattern in checks.items():
        if re.search(pattern, content):
            print_success(f"{check_name} found in app.py")
        else:
            print_error(f"{check_name} NOT found in app.py")
            passed = False
    
    return passed

def check_email_templates():
    """Verify email templates have logos"""
    print_header("3. Email Templates with Logo")
    
    files_to_check = {
        'email_utils.py': [
            ('send_email_verification', r'logo_url.*scanmydata_logo'),
            ('send_password_reset', r'logo_url.*scanmydata_logo'),
        ],
        'auth.py': [
            ('Firebase verification', r'verify_link = link_or_err.*logo_url'),
            ('Firebase password reset', r'reset_link = link_or_err.*logo_url'),
        ],
        'admin_api.py': [
            ('Admin email template', r'Create HTML email body.*logo_url'),
            ('SMTP test email', r'test_email.*logo_url'),
        ],
    }
    
    passed = True
    
    for filename, checks in files_to_check.items():
        if not os.path.exists(filename):
            print_error(f"File not found: {filename}")
            passed = False
            continue
        
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for check_name, pattern in checks:
            # Search in a reasonable context window
            if re.search(pattern, content, re.DOTALL):
                print_success(f"{filename} - {check_name}: Logo found")
            else:
                print_error(f"{filename} - {check_name}: Logo NOT found")
                passed = False
    
    return passed

def check_dark_mode_improvements():
    """Verify dark mode CSS improvements"""
    print_header("4. Dark Mode Improvements")
    
    base_html = "templates/base.html"
    
    if not os.path.exists(base_html):
        print_error(f"File not found: {base_html}")
        return False
    
    with open(base_html, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = {
        'Dark mode tooltip': r'Σκούρο θέμα.*κόπωση των ματιών',
        'Flash success dark': r'\[data-theme="dark"\] \.flash-success',
        'Flash error dark': r'\[data-theme="dark"\] \.flash-error',
        'Flash warning dark': r'\[data-theme="dark"\] \.flash-warning',
        'Flash info dark': r'\[data-theme="dark"\] \.flash-info',
        'Labels dark mode': r'\[data-theme="dark"\] label',
        'Headings dark mode': r'\[data-theme="dark"\] h1',
        'Links dark mode': r'\[data-theme="dark"\] a:not',
        'Tables dark mode': r'\[data-theme="dark"\] table',
    }
    
    passed = True
    for check_name, pattern in checks.items():
        if re.search(pattern, content):
            print_success(f"{check_name} implemented")
        else:
            print_error(f"{check_name} NOT found")
            passed = False
    
    return passed

def check_manifest():
    """Verify manifest.json configuration"""
    print_header("5. Manifest Configuration")
    
    manifest_file = "icons/site.webmanifest"
    
    if not os.path.exists(manifest_file):
        print_error(f"Manifest not found: {manifest_file}")
        return False
    
    with open(manifest_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = {
        'App name': r'"name":\s*"ScanmyData"',
        'Short name': r'"short_name"',
        'Icons array': r'"icons":\s*\[',
        '192px icon': r'192x192',
        '512px icon': r'512x512',
        'Theme color': r'"theme_color"',
        'Display mode': r'"display":\s*"standalone"',
    }
    
    passed = True
    for check_name, pattern in checks.items():
        if re.search(pattern, content):
            print_success(f"{check_name} configured")
        else:
            print_error(f"{check_name} NOT found")
            passed = False
    
    return passed

def check_base_html_logo_refs():
    """Verify base.html references logos correctly"""
    print_header("6. Base HTML Logo References")
    
    base_html = "templates/base.html"
    
    if not os.path.exists(base_html):
        print_error(f"File not found: {base_html}")
        return False
    
    with open(base_html, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = {
        'Favicon 96x96': r'/icons/favicon-96x96\.png',
        'Favicon SVG': r'/icons/favicon\.svg',
        'Favicon ICO': r'/icons/favicon\.ico',
        'Apple touch icon': r'/icons/apple-touch-icon\.png',
        'Manifest link': r'/icons/site\.webmanifest',
        'Light logo': r'/icons/scanmydata_logo_3000w\.png',
        'Dark logo': r'/icons/scanmydata_logo_dark_3000w\.png',
        'Logo class light': r'logo-light',
        'Logo class dark': r'logo-dark',
    }
    
    passed = True
    for check_name, pattern in checks.items():
        if re.search(pattern, content):
            print_success(f"{check_name} referenced")
        else:
            print_error(f"{check_name} NOT found")
            passed = False
    
    return passed

def verify_python_syntax():
    """Verify Python files have valid syntax"""
    print_header("7. Python Syntax Validation")
    
    python_files = [
        'app.py',
        'email_utils.py',
        'auth.py',
        'admin_api.py',
    ]
    
    passed = True
    for filename in python_files:
        if not os.path.exists(filename):
            print_error(f"File not found: {filename}")
            passed = False
            continue
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            compile(content, filename, 'exec')
            print_success(f"{filename} - Syntax valid")
        except SyntaxError as e:
            print_error(f"{filename} - Syntax error: {e}")
            passed = False
    
    return passed

def generate_summary(results):
    """Generate and print summary"""
    print_header("VALIDATION SUMMARY")
    
    total_checks = len(results)
    passed_checks = sum(1 for result in results.values() if result)
    failed_checks = total_checks - passed_checks
    
    print(f"Total checks: {total_checks}")
    print(f"{Colors.GREEN}Passed: {passed_checks}{Colors.END}")
    print(f"{Colors.RED}Failed: {failed_checks}{Colors.END}")
    print()
    
    for check_name, result in results.items():
        status = f"{Colors.GREEN}PASS{Colors.END}" if result else f"{Colors.RED}FAIL{Colors.END}"
        print(f"{check_name:.<50} {status}")
    
    print()
    
    if all(results.values()):
        print(f"{Colors.BOLD}{Colors.GREEN}✓ ALL VALIDATIONS PASSED!{Colors.END}")
        print()
        print_info("Next steps:")
        print("  1. Start the application: python app.py")
        print("  2. Test in browser: http://localhost:5001")
        print("  3. Verify icons display correctly")
        print("  4. Test dark mode toggle")
        print("  5. Send test emails and verify logo appears")
        return 0
    else:
        print(f"{Colors.BOLD}{Colors.RED}✗ SOME VALIDATIONS FAILED{Colors.END}")
        print()
        print_info("Please review the errors above and fix the issues.")
        return 1

def main():
    """Main validation function"""
    print(f"\n{Colors.BOLD}ScanmyData - Logo/Favicon/Email/Dark Mode Validation{Colors.END}")
    print(f"{Colors.YELLOW}Running comprehensive validation checks...{Colors.END}\n")
    
    # Change to repository root if needed
    if not os.path.exists('app.py'):
        if os.path.exists('Firebed_private/app.py'):
            os.chdir('Firebed_private')
        else:
            print_error("Cannot find app.py - are you in the correct directory?")
            return 1
    
    # Run all checks
    results = {
        'Icons Directory': check_icons_directory(),
        'Icons Route': check_icons_route(),
        'Email Templates': check_email_templates(),
        'Dark Mode CSS': check_dark_mode_improvements(),
        'Manifest Config': check_manifest(),
        'Base HTML Logos': check_base_html_logo_refs(),
        'Python Syntax': verify_python_syntax(),
    }
    
    # Generate summary
    return generate_summary(results)

if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Validation interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
