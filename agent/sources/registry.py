from agent.core.errors import UnknownSourceError
from agent.sources.base import Source
from agent.sources.fixture import FixtureSource

SOURCES: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (
        FixtureSource,
        # Phase 2: JobPostingsSource, FundingSource
    )
}


def get_source(name: str) -> type[Source]:
    try:
        return SOURCES[name]
    except KeyError:
        raise UnknownSourceError(name, sorted(SOURCES)) from None
