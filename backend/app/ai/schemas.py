from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ListingAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_type: str = ""
    style: str = ""
    colors: list[str] = Field(default_factory=list)
    subject: str = ""
    material: str = ""


class ListingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    description: str
    tags: list[str]
    seo_title: str = ""
    seo_description: str = ""
    seo_keywords: list[str] = Field(default_factory=list)
    attributes: ListingAttributes = Field(default_factory=ListingAttributes)
    warnings: list[str] = Field(default_factory=list)


class ProviderGenerationResult(BaseModel):
    output: ListingOutput
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_request_id: str | None = None
    retry_count: int = 0


class ProviderTargetedGenerationResult(BaseModel):
    output: dict[str, Any]
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_request_id: str | None = None
    retry_count: int = 0
