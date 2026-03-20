"""
Sector-based filtering and company selection
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SectorFilter:
    """Filter companies by GICS sector and industry."""

    @staticmethod
    def filter_by_sector(
        companies: List[Dict[str, Any]], sector: str
    ) -> List[Dict[str, Any]]:
        """
        Filter companies by GICS sector.

        Args:
            companies: List of company dictionaries
            sector: Sector name (e.g., 'Information Technology')

        Returns:
            Filtered list of companies
        """
        filtered = [
            c
            for c in companies
            if c.get("gics_sector", "").strip().lower() == sector.lower()
        ]
        logger.info(f"Filtered {len(filtered)} companies in sector: {sector}")
        return filtered

    @staticmethod
    def filter_by_industry(
        companies: List[Dict[str, Any]], industry: str
    ) -> List[Dict[str, Any]]:
        """
        Filter companies by GICS industry.

        Args:
            companies: List of company dictionaries
            industry: Industry name

        Returns:
            Filtered list of companies
        """
        filtered = [
            c
            for c in companies
            if c.get("gics_industry", "").strip().lower() == industry.lower()
        ]
        logger.info(f"Filtered {len(filtered)} companies in industry: {industry}")
        return filtered

    @staticmethod
    def filter_by_country(
        companies: List[Dict[str, Any]], country: str
    ) -> List[Dict[str, Any]]:
        """
        Filter companies by country.

        Args:
            companies: List of company dictionaries
            country: Country name

        Returns:
            Filtered list of companies
        """
        filtered = [
            c
            for c in companies
            if c.get("country", "").strip().lower() == country.lower()
        ]
        logger.info(f"Filtered {len(filtered)} companies in country: {country}")
        return filtered

    @staticmethod
    def filter_by_keywords(
        companies: List[Dict[str, Any]], *keywords
    ) -> List[Dict[str, Any]]:
        """
        Filter companies by keywords in security name or sector.

        Args:
            companies: List of company dictionaries
            keywords: Keywords to search for (case-insensitive)

        Returns:
            Filtered list of companies
        """
        filtered = []
        keywords_lower = [k.lower() for k in keywords]

        for company in companies:
            security = company.get("security", "").lower()
            sector = company.get("gics_sector", "").lower()
            industry = company.get("gics_industry", "").lower()

            # Check if any keyword appears in security, sector, or industry
            if any(
                kw in security or kw in sector or kw in industry
                for kw in keywords_lower
            ):
                filtered.append(company)

        logger.info(f"Filtered {len(filtered)} companies matching keywords: {keywords}")
        return filtered

    @staticmethod
    def get_it_companies(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Get all IT/Technology companies.

        Args:
            companies: List of company dictionaries

        Returns:
            List of IT/Technology companies
        """
        it_companies = SectorFilter.filter_by_keywords(
            companies,
            "information",
            "technology",
            "software",
            "semiconductor",
            "it",
            "tech",
        )
        logger.info(f"Extracted {len(it_companies)} IT/Technology companies")
        return it_companies
