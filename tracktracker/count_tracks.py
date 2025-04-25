import csv

def count_tracks(filename):
    tracks = 0
    episodes = 0
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 5:
                try:
                    track_count = int(row[-1])
                    tracks += track_count
                    episodes += 1
                except ValueError:
                    # Not a number, probably header or other text
                    pass
    
    return tracks, episodes

if __name__ == "__main__":
    filename = "nts_weekly_report_7days.csv"
    total_tracks, total_episodes = count_tracks(filename)
    print(f"Total episodes: {total_episodes}")
    print(f"Total tracks: {total_tracks}")
    print(f"Average tracks per episode: {total_tracks/total_episodes if total_episodes else 0:.1f}") 