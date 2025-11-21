"""
VAT Validation Service using EU VIES API
Validates Greek VAT numbers and retrieves business information
"""

import logging
import os
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    from zeep import Client
    from zeep.exceptions import Fault, TransportError
    ZEEP_AVAILABLE = True
except ImportError:
    ZEEP_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

log = logging.getLogger(__name__)


class VATValidator:
    """Validates VAT numbers using EU VIES web service"""
    
    VIES_WSDL = 'https://ec.europa.eu/taxation_customs/vies/services/checkVatService.wsdl'
    
    def __init__(self):
        self.client = None
        if ZEEP_AVAILABLE:
            try:
                self.client = Client(self.VIES_WSDL)
            except Exception as e:
                log.warning(f"Failed to initialize VIES client: {e}")
    
    def validate_greek_vat(self, vat_number: str) -> Dict[str, Any]:
        """
        Validate a Greek VAT number and retrieve business information
        
        Args:
            vat_number: The VAT number to validate (with or without EL prefix)
            
        Returns:
            Dictionary with validation result:
            {
                'valid': bool,
                'vat_number': str,
                'name': str or None,
                'address': str or None,
                'error': str or None
            }
        """
        # Default response
        result = {
            'valid': False,
            'vat_number': vat_number,
            'name': None,
            'address': None,
            'error': None
        }
        
        # Check if zeep is available
        if not ZEEP_AVAILABLE:
            result['error'] = 'VIES validation not available (zeep library not installed)'
            log.warning(result['error'])
            return result
        
        if not self.client:
            result['error'] = 'VIES client not initialized'
            log.warning(result['error'])
            return result
        
        # Clean VAT number
        clean_vat = self._clean_vat_number(vat_number)
        
        if not clean_vat:
            result['error'] = 'Invalid VAT number format'
            return result
        
        # Update result with cleaned VAT
        result['vat_number'] = clean_vat
        
        try:
            # Call VIES API
            response = self.client.service.checkVat(
                countryCode='EL',
                vatNumber=clean_vat
            )
            
            # Parse response
            result['valid'] = bool(response.valid)
            
            if result['valid']:
                result['name'] = self._clean_text(response.name) if hasattr(response, 'name') else None
                result['address'] = self._clean_text(response.address) if hasattr(response, 'address') else None
                
                log.info(f"VAT validation successful for {clean_vat}: {result['name']}")
            else:
                result['error'] = 'VAT number not found in VIES database'
                log.info(f"VAT validation failed for {clean_vat}: not valid")
                
        except Fault as e:
            error_msg = str(e)
            result['error'] = f'VIES service error: {error_msg}'
            log.error(f"VIES Fault for {clean_vat}: {error_msg}")
            
        except TransportError as e:
            error_msg = str(e)
            result['error'] = f'Network error: {error_msg}'
            log.error(f"VIES TransportError for {clean_vat}: {error_msg}")
            
        except Exception as e:
            error_msg = str(e)
            result['error'] = f'Unexpected error: {error_msg}'
            log.exception(f"Unexpected error validating VAT {clean_vat}")
        
        # If VIES failed, try Business Portal API as fallback
        if not result['valid'] and result['error']:
            log.info(f"VIES validation failed for {clean_vat}, trying Business Portal API fallback")
            fallback_result = self._validate_with_business_portal(clean_vat)
            if fallback_result['valid']:
                result.update(fallback_result)
                log.info(f"Business Portal fallback successful for {clean_vat}: {result['name']}")
            else:
                log.warning(f"Business Portal fallback also failed for {clean_vat}: {fallback_result.get('error', 'Unknown error')}")
        
        return result
    
    def _clean_vat_number(self, vat_number: str) -> Optional[str]:
        """
        Clean and validate VAT number format
        
        Args:
            vat_number: Raw VAT number input
            
        Returns:
            Cleaned VAT number (digits only) or None if invalid
        """
        if not vat_number:
            return None
        
        # Remove common prefixes and whitespace
        clean = vat_number.strip().upper()
        
        # Remove EL/GR prefix
        for prefix in ['EL', 'GR']:
            if clean.startswith(prefix):
                clean = clean[2:]
        
        # Remove any non-digit characters
        clean = ''.join(c for c in clean if c.isdigit())
        
        # Greek VAT numbers are 9 digits
        if len(clean) != 9:
            log.warning(f"Invalid VAT length: {len(clean)} (expected 9)")
            return None
        
        return clean
    
    def _clean_text(self, text: Optional[str]) -> Optional[str]:
        """Clean text from VIES response (remove extra whitespace, etc.)"""
        if not text:
            return None
        
        # Remove extra whitespace and newlines
        cleaned = ' '.join(text.split())
        
        return cleaned if cleaned else None
    
    def _validate_with_business_portal(self, vat_number: str) -> Dict[str, Any]:
        """
        Fallback validation using Business Portal API
        
        Args:
            vat_number: Clean VAT number (9 digits)
            
        Returns:
            Dictionary with validation result
        """
        result = {
            'valid': False,
            'vat_number': vat_number,
            'name': None,
            'address': None,
            'error': None
        }
        
        # Check if requests is available
        if not REQUESTS_AVAILABLE:
            result['error'] = 'Business Portal fallback not available (requests library not installed)'
            return result
        
        # Get API key from environment
        api_key = os.getenv('BUSINESS_PORTAL_KEY')
        if not api_key:
            result['error'] = 'Business Portal API key not configured (BUSINESS_PORTAL_KEY)'
            return result
        
        try:
            # Prepare API request
            url = 'https://opendata-api.businessportal.gr/api/opendata/v1/companies'
            headers = {
                'accept': 'application/json',
                'api_key': api_key
            }
            params = {
                'afm': vat_number.zfill(9),  # Ensure 9 digits with leading zeros
                'resultsSortBy': '+arGemi',
                'resultsOffset': 0,
                'resultsSize': 10
            }
            
            # Make API request
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            
            # Check if we got results
            search_results = data.get('searchResults', [])
            if not search_results:
                result['error'] = 'VAT number not found in Business Portal database'
                return result
            
            # Get the first result
            company = search_results[0]
            company_name = company.get('coNameEl')
            
            if company_name:
                result['valid'] = True
                result['name'] = self._clean_text(company_name)
                result['address'] = None  # Business Portal doesn't provide address in this endpoint
                log.info(f"Business Portal validation successful for {vat_number}: {result['name']}")
            else:
                result['error'] = 'Company name not found in Business Portal response'
                
        except requests.exceptions.Timeout:
            result['error'] = 'Business Portal API timeout'
            log.error(f"Business Portal timeout for {vat_number}")
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 'unknown'
            result['error'] = f'Business Portal HTTP error {status_code}: {str(e)}'
            log.error(f"Business Portal HTTP error for {vat_number}: {status_code}")
            
        except requests.exceptions.RequestException as e:
            result['error'] = f'Business Portal network error: {str(e)}'
            log.error(f"Business Portal network error for {vat_number}: {str(e)}")
            
        except Exception as e:
            result['error'] = f'Business Portal unexpected error: {str(e)}'
            log.exception(f"Business Portal unexpected error for {vat_number}")
        
        return result


# Singleton instance
_validator_instance = None


def get_validator() -> VATValidator:
    """Get or create validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = VATValidator()
    return _validator_instance


def validate_greek_vat(vat_number: str) -> Dict[str, Any]:
    """
    Convenience function to validate a Greek VAT number
    
    Args:
        vat_number: The VAT number to validate
        
    Returns:
        Validation result dictionary
    """
    validator = get_validator()
    return validator.validate_greek_vat(vat_number)


if __name__ == '__main__':
    # Test the validator
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    test_vat = sys.argv[1] if len(sys.argv) > 1 else '094014201'
    
    print(f"\nTesting VAT validation for: {test_vat}")
    print("-" * 60)
    
    result = validate_greek_vat(test_vat)
    
    print(f"Valid: {result['valid']}")
    print(f"VAT Number: {result['vat_number']}")
    print(f"Name: {result['name']}")
    print(f"Address: {result['address']}")
    
    if result['error']:
        print(f"Error: {result['error']}")
