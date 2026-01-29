# config.py
import os

class Config:
    # AWS Settings
    REGIONS = os.getenv("TARGET_REGIONS", "us-east-1,ap-east-1").split(",")
    
    # Logic: Regions to skip for specific account patterns
    REGION_EXCLUSIONS = {
        "ap-east-1": ["secondary"] # Skip ap-east-1 if account name contains 'secondary'
    }

    # Reporting Settings
    ENV_IDENTIFIERS = {
        "prod": ["prod", "production", "pr-"],
        "stg": ["stg", "staging"],
        "dev": ["dev", "development"]
    }


from config import Config

class Account:
    def __init__(self, acc_id, acc_name, organizational_unit, session):
        self.acc_id = acc_id
        self.acc_name = acc_name
        # ... (rest of init)

    def _should_scan_region(self, region):
        """Centralized logic to decide if a region should be scanned."""
        exclusions = Config.REGION_EXCLUSIONS.get(region, [])
        for keyword in exclusions:
            if keyword in self.acc_name.lower():
                return False
        return True

    def check_compliance(self):
        for region in Config.REGIONS:
            if not self._should_scan_region(region):
                continue
            
            try:
                self.generate_result(region)
            except Exception as e:
                logging.error(f"Failed to scan {self.acc_name} in {region}: {e}")

class ConfigRule:
    def set_tags(self, tags):
        # Priority list: Look for 'mox.application', then 'Application', then 'App'
        tag_map = {k['Key']: k['Value'] for k in tags}
        
        self.tags['Application'] = self._find_tag_value(tag_map, ['mox.application', 'Application', 'App'])
        self.tags['Owner'] = self._find_tag_value(tag_map, ['mox.owner', 'Owner', 'Team'])
        self.tags['Environment'] = self._find_tag_value(tag_map, ['mox.environment', 'Environment', 'Env'])

    def _find_tag_value(self, tag_map, keys_to_check):
        """Returns the first matching value from a list of possible keys."""
        for key in keys_to_check:
            if key in tag_map:
                return tag_map[key]
        return "UNSUPPORTED"

# In generate_report.py

# CHANGE: Use 'num' (number) instead of 'percentile' for absolute thresholds.
# Example: 0-80 is RED, 80-100 is GREEN (or however you define your gradient)
ws.conditional_formatting.add(f'D1:D{max_row}',
    ColorScaleRule(
        start_type='num', start_value=50, start_color=color_red,
        mid_type='num', mid_value=80, mid_color=color_yellow,
        end_type='num', end_value=100, end_color=color_green
    )
)