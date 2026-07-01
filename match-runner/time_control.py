from enum import Enum
import time

class TimeControlCategory(Enum):
    INCREMENT = 1
    MOVETIME = 2
    MOVESTOGO = 3
    MOVENODES = 4

class TimeControl:
    def __init__(
        self,
        category: TimeControlCategory,
        *,
        initial_time: int | None = None,
        increment: int | None = None,
        move_time: int | None = None,
        moves_to_go: int | None = None,
        nodes: int | None = None,
    ):
        self._category = category
        self._chess_clock = ChessClock()
        self._initial_time = initial_time
        self._increment = increment
        self._move_time = move_time
        self._moves_to_go = moves_to_go
        self._nodes = nodes

        if category is TimeControlCategory.INCREMENT:
            if self._initial_time is None or self._increment is None:
                raise ValueError("Increment mode needs initial_time and increment")

        elif category is TimeControlCategory.MOVETIME:
            if self._move_time is None:
                raise ValueError("Movetime mode needs move_time")

        elif category is TimeControlCategory.MOVESTOGO:
            if self._initial_time is None or self._moves_to_go is None:
                raise ValueError("Moves-to-go mode needs initial_time and moves_to_go")

        elif category is TimeControlCategory.MOVENODES:
            if self._nodes is None:
                raise ValueError("Movenodes mode needs nodes")

    def get_manager_object(self):
        return TimeManager(self)

    def get_category(self) -> TimeControlCategory:
        return self._category

    def set_category(self, category: TimeControlCategory):
        self._category = category

    def get_chess_clock(self):
        return self._chess_clock

    def set_chess_clock(self, chess_clock):
        self._chess_clock = chess_clock

    def get_initial_time(self) -> int | None:
        return self._initial_time

    def set_initial_time(self, initial_time: int | None):
        self._initial_time = initial_time

    def get_increment(self) -> int | None:
        return self._increment

    def set_increment(self, increment: int | None):
        self._increment = increment

    def get_move_time(self) -> int | None:
        return self._move_time

    def set_move_time(self, move_time: int | None):
        self._move_time = move_time

    def get_moves_to_go(self) -> int | None:
        return self._moves_to_go

    def set_moves_to_go(self, moves_to_go: int | None):
        self._moves_to_go = moves_to_go

    def get_nodes(self) -> int | None:
        return self._nodes

    def set_nodes(self, nodes: int | None):
        self._nodes = nodes
    
class TimeOutError(Exception):
    pass

class TimeManager(TimeControl):
    def __init__(self, tc: TimeControl):
        super().__init__(
            category=tc.get_category(),
            initial_time=tc.get_initial_time(),
            increment=tc.get_increment(),
            move_time=tc.get_move_time(),
            moves_to_go=tc.get_moves_to_go(),
            nodes=tc.get_nodes(),
        )

    def start_clock(self):
        self._chess_clock.start_clock()

    def probe_clock(self):
        elapsed_time = self._chess_clock.get_elapsed_time()
        if self._category is TimeControlCategory.INCREMENT:
            remaining_time = self._initial_time - elapsed_time

            if remaining_time <= 0:
                raise TimeOutError()

            return round(remaining_time)
            
        elif self._category is TimeControlCategory.MOVETIME:
            remaining_time = self._move_time - elapsed_time

            if remaining_time <= 0:
                raise TimeOutError()

            return round(remaining_time)
            
        elif self._category is TimeControlCategory.MOVESTOGO:
            
            remaining_time = self._initial_time - elapsed_time

            if remaining_time <= 0:
                raise TimeOutError()

            return round(remaining_time)

        elif self._category is TimeControlCategory.MOVENODES:
            return self._nodes

    def stop_clock(self):
        elapsed_time = self._chess_clock.stop_clock()
        if self._category is TimeControlCategory.INCREMENT:
            self._initial_time -= elapsed_time

            if self._initial_time <= 0:
                raise TimeOutError()

            self._initial_time = round(self._initial_time + self._increment)
            
        elif self._category is TimeControlCategory.MOVETIME:
            self._move_time -= elapsed_time

            if self._move_time <= 0:
                raise TimeOutError()

            self._move_time = round(self._move_time)
            
        elif self._category is TimeControlCategory.MOVESTOGO:
            
            self._initial_time -= elapsed_time
            self._moves_to_go -= 1

            if self._initial_time <= 0:
                raise TimeOutError()

            self._initial_time = round(self._initial_time)

        elif self._category is TimeControlCategory.MOVENODES:
            pass

    def stop_clock_after_timeout(self):
        self._chess_clock.stop_clock()

class ChessClock():
    def __init__(self, start_time: float = 0, running: bool = False):
        self._start_time = start_time
        self._running = running
        self._clock = self.get_time()

    def start_clock(self):
        self._clock = self.get_time()
        self._running = True

    def probe_clock(self):
        return self.get_elapsed_time()
        
    def stop_clock(self):
        elapsed_time = self.get_elapsed_time()
        self._running = False
        return elapsed_time

    def get_time(self):
        return time.perf_counter_ns() / 1_000_000

    def get_elapsed_time(self):
        if not self._running:
            return 0

        return self.get_time() - self._clock

    def get_start_time(self) -> float:
        return self._start_time

    def set_start_time(self, start_time: float):
        self._start_time = start_time

    def get_running(self) -> bool:
        return self._running

    def set_running(self, running: bool):
        self._running = running

    def get_clock(self) -> float:
        return self._clock

    def set_clock(self, clock: float):
        self._clock = clock
