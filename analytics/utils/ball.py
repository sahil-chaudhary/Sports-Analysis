import os
import yaml
import numpy as np
import matplotlib.pyplot as plt

from datetime import datetime
from dataclasses import dataclass
from scipy.spatial.distance import cdist
from typing import List, Tuple, Dict, Optional

cdir = os.path.dirname(os.path.abspath(__file__))


@dataclass
class PossessionEvent:
    timestamp: datetime
    ball_position: Tuple[float, float]
    possessing_team: str  # 'home' or 'away'
    player_id: int
    zone: str  # 'defensive', 'middle', 'attacking'
    duration: float
    distance_covered: float


class BallPossessionAnalyzer:
    def __init__(self, config_path: str = f'{cdir}/../config/config.yaml'):
        """
        Initialize Ball Possession Analyzer

        Args:
            config_path: Path to configuration file
        """
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.frame_rate = config['frame_rate']
        self.field_length = config['field']['length']
        self.field_width = config['field']['width']
        self.control_radius = config['thresholds']['ball_possession']['control_radius']
        self.min_possession_duration = config['thresholds']['ball_possession']['min_possession_duration']

        # Initialize tracking variables
        self.possession_events: List[PossessionEvent] = []
        self.current_possession: Optional[PossessionEvent] = None
        self.previous_ball_position: Optional[Tuple[float, float]] = None

        # Initialize possession statistics
        self.team_possession = {'home': 0.0, 'away': 0.0}
        self.zone_possession = {
            'defensive': 0.0,
            'middle': 0.0,
            'attacking': 0.0
        }

    def determine_zone(self, position: Tuple[float, float], team: str) -> str:
        """Determine which zone the ball is in"""
        y_coord = position[1]

        # Adjust zones based on attacking direction
        if team == 'home':
            if y_coord < self.field_length / 3:
                return 'defensive'
            elif y_coord < 2 * self.field_length / 3:
                return 'middle'
            else:
                return 'attacking'
        else:  # away team
            if y_coord < self.field_length / 3:
                return 'attacking'
            elif y_coord < 2 * self.field_length / 3:
                return 'middle'
            else:
                return 'defensive'

    def find_possessing_player(self,
                               ball_position: Tuple[float, float],
                               home_positions: List[Tuple[int, Tuple[float, float]]],
                               away_positions: List[Tuple[int, Tuple[float, float]]]) -> Tuple[str, int]:
        """
        Determine which player (if any) has possession of the ball

        Returns:
            Tuple of (team, player_id)
        """
        # Calculate distances to all players
        home_distances = cdist([ball_position], [pos[1]
                               for pos in home_positions])[0]
        away_distances = cdist([ball_position], [pos[1]
                               for pos in away_positions])[0]

        min_home_dist = np.min(home_distances)
        min_away_dist = np.min(away_distances)

        # Check if any player is within control radius
        if min_home_dist <= self.control_radius:
            player_idx = np.argmin(home_distances)
            return 'home', home_positions[player_idx][0]
        elif min_away_dist <= self.control_radius:
            player_idx = np.argmin(away_distances)
            return 'away', away_positions[player_idx][0]

        return 'none', -1

    def analyze_possession(self,
                           timestamp: datetime,
                           ball_position: Tuple[float, float],
                           home_positions: List[Tuple[int, Tuple[float, float]]],
                           away_positions: List[Tuple[int, Tuple[float, float]]]) -> Dict:
        """
        Analyze ball possession for the current frame

        Args:
            timestamp: Current timestamp
            ball_position: (x, y) position of the ball
            home_positions: List of (player_id, (x, y)) for home team
            away_positions: List of (player_id, (x, y)) for away team

        Returns:
            Dictionary containing possession metrics
        """
        # Find possessing player
        team, player_id = self.find_possessing_player(
            ball_position, home_positions, away_positions
        )

        # Calculate ball movement if we have previous position
        distance_covered = 0.0
        if self.previous_ball_position is not None:
            distance_covered = np.sqrt(
                (ball_position[0] - self.previous_ball_position[0]) ** 2 +
                (ball_position[1] - self.previous_ball_position[1]) ** 2
            )

        # Update or create possession event
        if team != 'none':
            zone = self.determine_zone(ball_position, team)

            if self.current_possession is None:
                # Start new possession
                self.current_possession = PossessionEvent(
                    timestamp=timestamp,
                    ball_position=ball_position,
                    possessing_team=team,
                    player_id=player_id,
                    zone=zone,
                    duration=0.0,
                    distance_covered=0.0
                )
            elif self.current_possession.possessing_team == team:
                # Update current possession
                duration = (
                    timestamp - self.current_possession.timestamp).total_seconds()
                # print(duration)
                self.current_possession.duration = duration
                self.current_possession.distance_covered += distance_covered

                # Update possession statistics if minimum duration met
                if duration >= self.min_possession_duration:
                    self.team_possession[team] = duration
                    self.zone_possession[zone] = duration
            else:
                # Change of possession
                if self.current_possession.duration >= self.min_possession_duration:
                    self.possession_events.append(self.current_possession)

                # Start new possession
                self.current_possession = PossessionEvent(
                    timestamp=timestamp,
                    ball_position=ball_position,
                    possessing_team=team,
                    player_id=player_id,
                    zone=zone,
                    duration=0.0,
                    distance_covered=0.0
                )
        else:
            # End current possession if minimum duration met
            if self.current_possession is not None:
                duration = (
                    timestamp - self.current_possession.timestamp).total_seconds()
                if duration >= self.min_possession_duration:
                    self.possession_events.append(self.current_possession)
                self.current_possession = None

        self.previous_ball_position = ball_position

        return {
            'possessing_team': team,
            'player_id': player_id,
            'zone': self.determine_zone(ball_position, team) if team != 'none' else 'none',
            'distance_covered': distance_covered
        }

    def get_possession_stats(self, time_window: float = None) -> Dict:
        """
        Calculate possession statistics

        Args:
            time_window: Optional time window in seconds to analyze
                        (None for all events)
        """
        if not self.possession_events:
            return {}

        # Filter events by time window if specified
        events = self.possession_events
        if time_window is not None:
            latest_time = self.possession_events[-1].timestamp
            cutoff_time = latest_time - datetime.timedelta(seconds=time_window)
            events = [e for e in events if e.timestamp >= cutoff_time]

        # Calculate total durations
        total_time = sum(e.duration for e in events)
        if total_time == 0:
            return {}

        # Calculate team possession percentages
        team_possession = {
            'home': sum(e.duration for e in events if e.possessing_team == 'home'),
            'away': sum(e.duration for e in events if e.possessing_team == 'away')
        }
        # print(len(events))
        team_percentages = {
            team: (duration / total_time) * 100
            for team, duration in team_possession.items()
        }

        # Calculate zone percentages
        zone_possession = {
            zone: sum(e.duration for e in events if e.zone == zone)
            for zone in ['defensive', 'middle', 'attacking']
        }
        zone_percentages = {
            zone: (duration / total_time) * 100
            for zone, duration in zone_possession.items()
        }

        # Calculate player possession times
        player_possession = {}
        for event in events:
            key = (event.possessing_team, event.player_id)
            if key not in player_possession:
                player_possession[key] = 0.0
            player_possession[key] += event.duration

        return {
            'team_possession': team_percentages,
            'zone_possession': zone_percentages,
            'player_possession': player_possession,
            'total_time': total_time,
            'possession_counts': {
                'home': len([e for e in events if e.possessing_team == 'home']),
                'away': len([e for e in events if e.possessing_team == 'away'])
            }
        }

    def visualize_possession(self, time_window: float = None, save_path: str = None, show: bool = True):
        """Visualize possession statistics"""
        stats = self.get_possession_stats(time_window)
        if not stats:
            return

        plt.figure(figsize=(15, 5))

        # Team possession pie chart
        plt.subplot(131)
        team_possession = stats['team_possession']
        plt.pie([team_possession['home'], team_possession['away']],
                labels=['Home', 'Away'],
                colors=['blue', 'red'],
                autopct='%1.1f%%')
        plt.title('Team Possession')

        # Zone possession bar chart
        plt.subplot(132)
        zone_possession = stats['zone_possession']
        zones = list(zone_possession.keys())
        percentages = list(zone_possession.values())
        plt.bar(zones, percentages)
        plt.title('Zone Possession')
        plt.ylabel('Possession %')
        plt.xticks(rotation=45)

        # Possession map
        plt.subplot(133)
        # print(self.possession_events[1])
        events = [e for e in self.possession_events
                  if time_window is None or
                  (self.possession_events[-1].timestamp - e.timestamp).total_seconds() <= time_window]

        # Plot field
        plt.plot([0, self.field_length], [0, 0], 'k-')
        plt.plot([0, self.field_length], [
                 self.field_width, self.field_width], 'k-')
        plt.plot([0, 0], [0, self.field_width], 'k-')
        plt.plot([self.field_length, self.field_length],
                 [0, self.field_width], 'k-')

        # Plot possession points
        for event in events:
            color = 'blue' if event.possessing_team == 'home' else 'red'
            size = event.duration * 100  # Scale point size by possession duration
            plt.scatter(event.ball_position[0], event.ball_position[1],
                        c=color, s=size, alpha=0.5)

        plt.title('Possession Map')
        plt.xlabel('Field Length (m)')
        plt.ylabel('Field Width (m)')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path)

        if show:
            plt.show()

    def data_possession_flow(self, last_n_events: int = 20):
        """Data possession flow over time"""
        if not self.possession_events:
            return

        # Get last N events
        events = self.possession_events[-last_n_events:]

        # Create timeline
        times = [((e.timestamp - events[0].timestamp).total_seconds(),
                  e.duration) for e in events]
        teams = [1 if e.possessing_team == 'home' else 2 for e in events]

        x = {1: "left", 2: "right"}

        lists = []
        for i in range(len(times)):
            lists.append(
                {"start": times[i][0], "duration": times[i][1], "color": f'{x[teams[i]]}'})

        return lists

    def plot_possession_flow(self, last_n_events: int = 20, save_path: str = None, show: bool = True):
        """Plot possession flow over time"""
        if not self.possession_events:
            return

        # Get last N events
        events = self.possession_events[-last_n_events:]

        plt.figure(figsize=(15, 5))

        # Create timeline
        times = [((e.timestamp - events[0].timestamp).total_seconds(),
                  e.duration) for e in events]

        time_starts = [t[0] for t in times]
        time_ends = [t[0] + t[1] for t in times]

        lines = []
        if time_starts[0] != 0.0:
            lines.append(((0.0, time_starts[0]), (1, 1), 'none'))
        for i in range(len(time_starts)):
            if i != 0:
                if time_starts[i] != time_ends[i-1]:
                    lines.append(
                        ((time_ends[i-1], time_starts[i]), (1, 1), 'none'))
                lines.append(((time_starts[i], time_ends[i]), (1, 1), f'{events[i].possessing_team}'))
            else:
                lines.append(((time_starts[i], time_ends[i]), (1, 1), f'{events[i].possessing_team}'))

        # Plot from timestart[i] to timeend[i] for each team
        for i in range(len(lines)):
            if lines[i][2] == 'none':
                color = 'gray'
            elif lines[i][2] == 'home':
                color = 'blue'
            else:
                color = 'red'
            
            plt.fill_between(lines[i][0], lines[i][1],
                             step='post', alpha=1, color=color)

        plt.title('Possession Flow')
        plt.grid(False)

        # Don't show axes numbers
        plt.yticks([])
        plt.xticks([])
        
        # remove the rectangular frame around the plot
        plt.box(False)

        if save_path:
            plt.savefig(save_path)

        if show:
            plt.show()
