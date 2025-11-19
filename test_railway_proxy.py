#!/usr/bin/env python3
"""
Test script for Railway email proxy functionality
"""
import os
import sys
import json

def test_email_utils_import():
    """Test that email_utils can be imported"""
    try:
        import email_utils
        print("✅ email_utils imported successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to import email_utils: {e}")
        return False


def test_railway_proxy_constants():
    """Test that Railway proxy constants are defined"""
    try:
        import email_utils
        
        # Check if RAILWAY_PROXY_URL constant exists
        assert hasattr(email_utils, 'RAILWAY_PROXY_URL'), "RAILWAY_PROXY_URL not defined"
        print(f"✅ RAILWAY_PROXY_URL constant defined: '{email_utils.RAILWAY_PROXY_URL}'")
        
        return True
    except Exception as e:
        print(f"❌ Railway proxy constants test failed: {e}")
        return False


def test_get_email_provider():
    """Test that get_email_provider recognizes railway_proxy"""
    try:
        import email_utils
        
        # Test that railway_proxy is in the valid providers list
        # We'll do this by checking the function code
        import inspect
        source = inspect.getsource(email_utils.get_email_provider)
        
        assert 'railway_proxy' in source, "railway_proxy not in get_email_provider"
        print("✅ get_email_provider recognizes railway_proxy")
        
        return True
    except Exception as e:
        print(f"❌ get_email_provider test failed: {e}")
        return False


def test_send_railway_proxy_email_exists():
    """Test that send_railway_proxy_email function exists"""
    try:
        import email_utils
        
        assert hasattr(email_utils, 'send_railway_proxy_email'), "send_railway_proxy_email function not found"
        assert callable(email_utils.send_railway_proxy_email), "send_railway_proxy_email is not callable"
        
        print("✅ send_railway_proxy_email function exists")
        return True
    except Exception as e:
        print(f"❌ send_railway_proxy_email test failed: {e}")
        return False


def test_send_email_routing():
    """Test that send_email can route to railway_proxy"""
    try:
        import email_utils
        import inspect
        
        source = inspect.getsource(email_utils.send_email)
        
        assert 'railway_proxy' in source, "railway_proxy not in send_email routing"
        assert 'send_railway_proxy_email' in source, "send_railway_proxy_email not called in routing"
        
        print("✅ send_email routing includes railway_proxy")
        return True
    except Exception as e:
        print(f"❌ send_email routing test failed: {e}")
        return False


def test_app_settings_save():
    """Test that app.py can handle railway_proxy settings"""
    try:
        # Read app.py and check for railway_proxy handling
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check that railway_proxy is in the valid providers list
        assert "'railway_proxy'" in content, "railway_proxy not in app.py settings"
        
        # Check that railway_proxy_url is saved
        assert 'railway_proxy_url' in content, "railway_proxy_url not saved in app.py"
        
        print("✅ app.py handles railway_proxy settings")
        return True
    except Exception as e:
        print(f"❌ app.py settings test failed: {e}")
        return False


def test_admin_api_email_config():
    """Test that admin_api.py includes railway_proxy in email config"""
    try:
        # Read admin_api.py and check for railway_proxy
        with open('admin_api.py', 'r') as f:
            content = f.read()
        
        assert 'railway_proxy' in content, "railway_proxy not in admin_api.py"
        
        print("✅ admin_api.py includes railway_proxy configuration")
        return True
    except Exception as e:
        print(f"❌ admin_api.py test failed: {e}")
        return False


def test_settings_template():
    """Test that settings template includes railway_proxy option"""
    try:
        with open('templates/admin/settings.html', 'r') as f:
            content = f.read()
        
        assert 'railway_proxy' in content, "railway_proxy option not in settings template"
        assert 'railway_proxy_url' in content, "railway_proxy_url field not in settings template"
        assert 'Railway Proxy' in content, "Railway Proxy label not in settings template"
        
        print("✅ Settings template includes Railway Proxy option")
        return True
    except Exception as e:
        print(f"❌ Settings template test failed: {e}")
        return False


def test_railway_service_files():
    """Test that Railway service files exist"""
    try:
        import os
        
        files = [
            'railway-email-relay/server.js',
            'railway-email-relay/package.json',
            'railway-email-relay/railway.json',
            'railway-email-relay/README.md',
            'railway-email-relay/.gitignore'
        ]
        
        for file in files:
            assert os.path.exists(file), f"File not found: {file}"
            print(f"  ✓ {file}")
        
        print("✅ All Railway service files exist")
        return True
    except Exception as e:
        print(f"❌ Railway service files test failed: {e}")
        return False


def test_railway_package_json():
    """Test that package.json has correct dependencies"""
    try:
        with open('railway-email-relay/package.json', 'r') as f:
            pkg = json.load(f)
        
        # Check required dependencies
        deps = pkg.get('dependencies', {})
        assert 'express' in deps, "express not in dependencies"
        assert 'nodemailer' in deps, "nodemailer not in dependencies"
        assert 'cors' in deps, "cors not in dependencies"
        
        # Check scripts
        scripts = pkg.get('scripts', {})
        assert 'start' in scripts, "start script not defined"
        
        print("✅ package.json has correct dependencies and scripts")
        return True
    except Exception as e:
        print(f"❌ package.json test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("Railway Email Proxy - Implementation Tests")
    print("=" * 60)
    print()
    
    tests = [
        ("Email Utils Import", test_email_utils_import),
        ("Railway Proxy Constants", test_railway_proxy_constants),
        ("Email Provider Recognition", test_get_email_provider),
        ("Send Railway Proxy Email Function", test_send_railway_proxy_email_exists),
        ("Email Routing", test_send_email_routing),
        ("App Settings Save", test_app_settings_save),
        ("Admin API Config", test_admin_api_email_config),
        ("Settings Template", test_settings_template),
        ("Railway Service Files", test_railway_service_files),
        ("Railway Package.json", test_railway_package_json),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n📝 Testing: {name}")
        print("-" * 60)
        result = test_func()
        results.append((name, result))
        print()
    
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} {name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Implementation is complete.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
