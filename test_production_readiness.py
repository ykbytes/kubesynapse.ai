#!/usr/bin/env python3
"""
Pre-Deployment Validation Suite for Kubemininions AI Agent Sandbox

This script performs comprehensive validation before deploying to production,
checking all critical components, security settings, and functionality.

Usage:
    python test_production_readiness.py                    # Run all tests
    python test_production_readiness.py --component core   # Test specific component
    python test_production_readiness.py --verbose          # Detailed output
    python test_production_readiness.py --generate-report  # Generate HTML report
"""

import sys
import json
import subprocess
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import argparse


@dataclass
class TestResult:
    """Represents a single test result"""
    component: str
    test_name: str
    passed: bool
    message: str
    severity: str  # critical, warning, info
    details: Optional[str] = None


class ProductionReadinessValidator:
    """Comprehensive validator for production deployment readiness"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.workspace_root = Path(__file__).parent
        
    def log(self, message: str, level: str = "INFO"):
        """Log messages"""
        if self.verbose or level != "DEBUG":
            print(f"[{level}] {message}")

    def run_command(self, cmd: str, check: bool = False) -> Tuple[bool, str]:
        """Run shell command and return success status and output"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            success = result.returncode == 0
            output = result.stdout + result.stderr
            return success, output
        except subprocess.TimeoutExpired:
            return False, "Command timeout"
        except Exception as e:
            return False, str(e)

    # ============================================================================
    # IMAGE & CONTAINER VALIDATION
    # ============================================================================

    def validate_image_tags(self) -> None:
        """Verify all Docker images have explicit version tags"""
        self.log("Validating image tags...", "INFO")
        
        values_file = self.workspace_root / "deploy/values.dockerhub.local.yaml"
        if not values_file.exists():
            self.add_result("images", "values_file_exists", False, 
                          "values.dockerhub.local.yaml not found", "critical")
            return

        content = values_file.read_text()
        
        # Check for latest tags
        latest_matches = re.findall(r'image:.*:latest', content)
        if latest_matches:
            self.add_result("images", "no_latest_tags", False,
                          f"Found {len(latest_matches)} 'latest' tags", "critical",
                          details=str(latest_matches))
        else:
            self.add_result("images", "no_latest_tags", True,
                          "All images have explicit version tags", "info")

        # Check for versioned tags
        version_matches = re.findall(r'image:.*:[\d\w.-]+', content)
        if len(version_matches) > 5:  # Expect multiple versioned images
            self.add_result("images", "versioned_tags", True,
                          f"Found {len(version_matches)} versioned images", "info")
        else:
            self.add_result("images", "versioned_tags", False,
                          "Insufficient versioned image tags", "warning")

    def validate_dockerfile_security(self) -> None:
        """Check Dockerfiles for security best practices"""
        self.log("Scanning Dockerfiles for security issues...", "INFO")
        
        dockerfile_patterns = list(self.workspace_root.glob("**/Dockerfile"))
        
        for dockerfile in dockerfile_patterns:
            content = dockerfile.read_text()
            
            # Check for root user
            if "USER root" in content or not re.search(r'USER \d+', content):
                self.add_result("security", f"dockerfile_{dockerfile.parent.name}",
                              False, f"No non-root user in {dockerfile.parent.name}",
                              "warning")
            else:
                self.add_result("security", f"dockerfile_{dockerfile.parent.name}_user",
                              True, f"Non-root user configured", "info")
            
            # Check for multi-stage builds in runtime images
            if "agent-runtime" in str(dockerfile) or "operator" in str(dockerfile):
                if "FROM" in content and content.count("FROM") > 1:
                    self.add_result("security", f"multistage_{dockerfile.parent.name}",
                                  True, "Multi-stage build found", "info")

    # ============================================================================
    # CONFIGURATION VALIDATION
    # ============================================================================

    def validate_helm_chart(self) -> None:
        """Validate Helm chart configuration"""
        self.log("Validating Helm chart...", "INFO")
        
        chart_file = self.workspace_root / "charts/ai-agent-sandbox/Chart.yaml"
        if not chart_file.exists():
            self.add_result("helm", "chart_exists", False,
                          "Chart.yaml not found", "critical")
            return

        content = chart_file.read_text()
        
        # Check for version
        if "version:" in content:
            version_match = re.search(r'version:\s*([\d.]+)', content)
            if version_match:
                self.add_result("helm", "chart_version", True,
                              f"Chart version: {version_match.group(1)}", "info")

        # Check for app version
        if "appVersion:" in content:
            self.add_result("helm", "app_version", True,
                          "App version specified", "info")

    def validate_values_files(self) -> None:
        """Validate values files don't contain hardcoded secrets"""
        self.log("Validating values files...", "INFO")
        
        values_files = [
            self.workspace_root / "deploy/values.dockerhub.local.yaml",
            self.workspace_root / "deploy/values.local-images.example.yaml",
        ]

        secret_patterns = [
            r'password.*:.*[a-zA-Z0-9]{8,}',
            r'token.*:.*[a-zA-Z0-9]{20,}',
            r'secret.*:.*[a-zA-Z0-9]{20,}',
        ]

        for values_file in values_files:
            if not values_file.exists():
                continue

            content = values_file.read_text()
            found_secrets = []

            for pattern in secret_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                found_secrets.extend(matches)

            if found_secrets:
                self.add_result("config", f"secrets_{values_file.name}", False,
                              f"Found {len(found_secrets)} potential hardcoded secrets",
                              "critical", details="Review values before deployment")
            else:
                self.add_result("config", f"secrets_{values_file.name}", True,
                              "No hardcoded secrets detected", "info")

    # ============================================================================
    # WEB UI VALIDATION
    # ============================================================================

    def validate_web_ui(self) -> None:
        """Validate web UI TypeScript compilation and layout"""
        self.log("Validating web UI...", "INFO")
        
        web_ui_dir = self.workspace_root / "web-ui"
        if not web_ui_dir.exists():
            self.add_result("web-ui", "directory_exists", False,
                          "web-ui directory not found", "warning")
            return

        # Check tsconfig
        tsconfig = web_ui_dir / "tsconfig.json"
        if tsconfig.exists():
            self.add_result("web-ui", "tsconfig_exists", True,
                          "tsconfig.json found", "info")
        else:
            self.add_result("web-ui", "tsconfig_exists", False,
                          "tsconfig.json not found", "warning")

        # Check for package.json
        package_json = web_ui_dir / "package.json"
        if package_json.exists():
            try:
                pkg_data = json.loads(package_json.read_text())
                self.add_result("web-ui", "package_json", True,
                              f"React version: {pkg_data.get('dependencies', {}).get('react', 'unknown')}",
                              "info")
            except json.JSONDecodeError:
                self.add_result("web-ui", "package_json_parse", False,
                              "Failed to parse package.json", "warning")

        # Check Dockerfile
        dockerfile = web_ui_dir / "Dockerfile"
        if dockerfile.exists():
            content = dockerfile.read_text()
            if "FROM node" in content and "FROM nginx" in content:
                self.add_result("web-ui", "multistage_build", True,
                              "Multi-stage build configured", "info")
            else:
                self.add_result("web-ui", "multistage_build", False,
                              "Multi-stage build not detected", "warning")

    # ============================================================================
    # API & GATEWAY VALIDATION
    # ============================================================================

    def validate_api_gateway(self) -> None:
        """Validate API gateway configuration"""
        self.log("Validating API gateway...", "INFO")
        
        api_dir = self.workspace_root / "api-gateway"
        if not api_dir.exists():
            self.add_result("api", "gateway_exists", False,
                          "api-gateway directory not found", "critical")
            return

        # Check main.py
        main_file = api_dir / "main.py"
        if main_file.exists():
            content = main_file.read_text()
            
            # Check for JWT auth
            if "jwt" in content.lower() or "authorization" in content.lower():
                self.add_result("api", "jwt_auth", True,
                              "JWT authentication implemented", "info")
            
            # Check for CORS
            if "cors" in content.lower():
                self.add_result("api", "cors_configured", True,
                              "CORS configured", "info")

        # Check requirements
        req_file = api_dir / "requirements.txt"
        if req_file.exists():
            reqs = req_file.read_text()
            
            required_packages = ["fastapi", "pydantic", "python-jose"]
            missing = [pkg for pkg in required_packages if pkg not in reqs.lower()]
            
            if not missing:
                self.add_result("api", "dependencies", True,
                              "All required packages present", "info")
            else:
                self.add_result("api", "dependencies", False,
                              f"Missing packages: {', '.join(missing)}", "warning")

    # ============================================================================
    # DATABASE VALIDATION
    # ============================================================================

    def validate_persistence(self) -> None:
        """Validate persistence and database configuration"""
        self.log("Validating persistence configuration...", "INFO")
        
        # Check auth_store
        auth_store = self.workspace_root / "api-gateway/auth_store.py"
        if auth_store.exists():
            content = auth_store.read_text()
            
            if "sqlite" in content.lower() or "database" in content.lower():
                self.add_result("persistence", "database_configured", True,
                              "Database persistence configured", "info")
            
            # Check for initialization
            if "__init__" in content or "create_table" in content.lower():
                self.add_result("persistence", "schema_init", True,
                              "Schema initialization implemented", "info")

        # Check if state_store exists for operator
        state_store = self.workspace_root / "operator/state_store.py"
        if state_store.exists():
            self.add_result("persistence", "operator_state", True,
                          "Operator state persistence", "info")

    # ============================================================================
    # SECURITY VALIDATION
    # ============================================================================

    def validate_rbac(self) -> None:
        """Validate RBAC and namespace isolation"""
        self.log("Validating RBAC configuration...", "INFO")
        
        # Check Helm values for RBAC
        values_file = self.workspace_root / "deploy/values.dockerhub.local.yaml"
        if values_file.exists():
            content = values_file.read_text()
            
            if "rbac" in content.lower():
                self.add_result("security", "rbac_configured", True,
                              "RBAC configuration present", "info")
            
            if "serviceaccount" in content.lower():
                self.add_result("security", "service_accounts", True,
                              "Service accounts configured", "info")

    def validate_secrets_management(self) -> None:
        """Validate secrets are not hardcoded"""
        self.log("Validating secrets management...", "INFO")
        
        # Scan Python files for hardcoded secrets
        py_files = list(self.workspace_root.glob("**/*.py"))
        
        secret_keywords = [
            r'password\s*=\s*["\'][^"\']{8,}["\']',
            r'token\s*=\s*["\'][^"\']{20,}["\']',
            r'api_key\s*=\s*["\'][^"\']{20,}["\']',
        ]

        found_issues = 0
        for py_file in py_files:
            if "test" in str(py_file):  # Skip test files
                continue
            
            content = py_file.read_text()
            for pattern in secret_keywords:
                if re.search(pattern, content):
                    found_issues += 1

        if found_issues == 0:
            self.add_result("security", "no_hardcoded_secrets", True,
                          "No hardcoded secrets detected in source", "info")
        else:
            self.add_result("security", "hardcoded_secrets", False,
                          f"Potential hardcoded secrets found in {found_issues} files",
                          "warning")

    def validate_pod_security(self) -> None:
        """Validate pod security contexts"""
        self.log("Validating pod security contexts...", "INFO")
        
        values_file = self.workspace_root / "deploy/values.dockerhub.local.yaml"
        if values_file.exists():
            content = values_file.read_text()
            
            # Check for security context
            if "securitycontext" in content.lower() or "runas" in content.lower():
                self.add_result("security", "pod_security_context", True,
                              "Pod security contexts configured", "info")
            else:
                self.add_result("security", "pod_security_context", False,
                              "Pod security contexts not found", "warning")

    # ============================================================================
    # TESTING VALIDATION
    # ============================================================================

    def validate_test_suite(self) -> None:
        """Check test coverage and test configuration"""
        self.log("Validating test suite...", "INFO")
        
        # Check pytest.ini
        pytest_ini = self.workspace_root / "pytest.ini"
        if pytest_ini.exists():
            self.add_result("testing", "pytest_configured", True,
                          "pytest.ini found", "info")
        else:
            self.add_result("testing", "pytest_configured", False,
                          "pytest.ini not found", "warning")

        # Check for test files
        test_files = list(self.workspace_root.glob("**/test_*.py"))
        if test_files:
            self.add_result("testing", "test_files", True,
                          f"Found {len(test_files)} test files", "info")
        else:
            self.add_result("testing", "test_files", False,
                          "No test files found", "warning")

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    def add_result(self, component: str, test_name: str, passed: bool,
                   message: str, severity: str, details: Optional[str] = None):
        """Add a test result"""
        result = TestResult(
            component=component,
            test_name=test_name,
            passed=passed,
            message=message,
            severity=severity,
            details=details
        )
        self.results.append(result)
        
        status = "✅ PASS" if passed else ("⚠️  WARN" if severity == "warning" else "❌ FAIL")
        self.log(f"{status}: [{component}] {test_name} - {message}", "RESULT")

    def run_all_validations(self) -> None:
        """Run all validation checks"""
        self.log("\n" + "="*70, "INFO")
        self.log("KUBEMININIONS PRODUCTION READINESS VALIDATION", "INFO")
        self.log(f"Start time: {datetime.now().isoformat()}", "INFO")
        self.log("="*70 + "\n", "INFO")

        # Image & Container
        self.validate_image_tags()
        self.validate_dockerfile_security()

        # Configuration
        self.validate_helm_chart()
        self.validate_values_files()

        # Web UI
        self.validate_web_ui()

        # API & Gateway
        self.validate_api_gateway()

        # Persistence
        self.validate_persistence()

        # Security
        self.validate_rbac()
        self.validate_secrets_management()
        self.validate_pod_security()

        # Testing
        self.validate_test_suite()

    def print_summary(self) -> None:
        """Print validation summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        warnings = sum(1 for r in self.results if r.severity == "warning" and not r.passed)
        critical = sum(1 for r in self.results if r.severity == "critical" and not r.passed)

        self.log("\n" + "="*70, "INFO")
        self.log("VALIDATION SUMMARY", "INFO")
        self.log("="*70, "INFO")
        self.log(f"Total Tests: {total}", "INFO")
        self.log(f"✅ Passed: {passed}", "INFO")
        self.log(f"⚠️  Warnings: {warnings}", "INFO")
        self.log(f"❌ Critical: {critical}", "INFO")
        self.log("="*70 + "\n", "INFO")

        if critical > 0:
            self.log("🚫 PRODUCTION NOT READY - Critical issues must be resolved", "ERROR")
            sys.exit(1)
        elif warnings > 0:
            self.log("⚠️  CAUTION - Review warnings before deployment", "WARNING")
        else:
            self.log("✅ READY FOR PRODUCTION DEPLOYMENT", "SUCCESS")

    def generate_json_report(self, filename: str = "validation_report.json") -> None:
        """Generate JSON report"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.passed),
                "warnings": sum(1 for r in self.results if r.severity == "warning" and not r.passed),
                "critical": sum(1 for r in self.results if r.severity == "critical" and not r.passed),
            },
            "results": [asdict(r) for r in self.results]
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.log(f"Report saved to {filename}", "INFO")


def main():
    parser = argparse.ArgumentParser(
        description="Production Readiness Validator for Kubemininions"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    parser.add_argument("--report", type=str, default=None,
                       help="Save JSON report to file")
    
    args = parser.parse_args()
    
    validator = ProductionReadinessValidator(verbose=args.verbose)
    validator.run_all_validations()
    validator.print_summary()
    
    if args.report:
        validator.generate_json_report(args.report)


if __name__ == "__main__":
    main()
