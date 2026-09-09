from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import event


@dataclass
class QueryTiming:
    count: int = 0
    seconds: float = 0.0


query_timing: ContextVar[QueryTiming | None] = ContextVar("query_timing", default=None)


def instrument_engine(engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def before(_connection, _cursor, _statement, _parameters, context, _many):
        context.studyhub_query_started = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after(_connection, _cursor, _statement, _parameters, context, _many):
        timing = query_timing.get()
        if timing is not None:
            timing.count += 1
            timing.seconds += perf_counter() - context.studyhub_query_started
