from agent.core.errors import UnknownSourceError
from agent.sources.base import Source
from agent.sources.fixture import FixtureSource
from agent.sources.funding import FundingNewsSource
from agent.sources.job_posts import JobPostingsSource

SOURCES: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (
        FixtureSource,
        JobPostingsSource,
        FundingNewsSource,
    )
}


def get_source(name: str) -> type[Source]:
    try:
        return SOURCES[name]
    except KeyError:
        raise UnknownSourceError(name, sorted(SOURCES)) from None
