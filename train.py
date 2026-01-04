import pygame
import pymunk
import numpy as np
import os
import glob
import random
import math
from src.cave_environment.environment import CaveEnvironment
from src.cave_environment.spritesheet import SpriteSheet
from src.entities.submarine import Submarine
from src.sonar.sensors import Sonar
from src.ai.agent import DoubleDQNAgent

# --- CONFIGURATION ---
LOAD_MODEL = True  # Set False to restart fresh
NUM_EPISODES = 50000
MAX_STEPS = 4000
BATCH_SIZE = 128
TARGET_UPDATE = 1000
SAVE_INTERVAL = 1000
EPSILON_DECAY = 0.99995

# --- STRICT 13-POINT RULE SET ---
FIXED_RULES = {
    'wall_penalty': -50.0,
    'goal_reward': 100.0,
    'battery_reward': 10.0,
    'all_batteries_bonus': 50.0,
    'forward_drive_mult': 0.5,
    'glide_reward': 0.05,
    'death_penalty': -10.0,
    'obstacle_hit': -5.0,
    'stagnation_pen': -5.0
}

CURRICULUM = {0: FIXED_RULES, 1: FIXED_RULES, 2: FIXED_RULES, 3: FIXED_RULES, 4: FIXED_RULES}

MAP_FILES = [
    "src/cave_environment/map1_basic.csv",
    "src/cave_environment/map2_jagged.csv",
    "src/cave_environment/map3_jagged_long_narrow.csv",
    "src/cave_environment/map4_zigzag.csv",
    "src/cave_environment/map5_one_battery.csv",
    "src/cave_environment/map6_three_battery.csv",
    "src/cave_environment/map7_obstacle_simple.csv",
    "src/cave_environment/map8_obstacle_hard.csv",
]

pygame.init()
screen = pygame.display.set_mode((1200, 800))
pygame.display.set_caption("Submarine AI Training (Press TAB to Watch)")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 25)


def load_level(map_index, spritesheet):
    try:
        filename = MAP_FILES[map_index]
        env = CaveEnvironment(filename, spritesheet)
        new_space = pymunk.Space()
        new_space.gravity = (0, 0)
        for tile in env.environment_tiles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (tile.rect.centerx, tile.rect.centery)
            shape = pymunk.Poly.create_box(body, (tile.rect.width, tile.rect.height))
            shape.filter = pymunk.ShapeFilter(group=1)
            new_space.add(body, shape)
        for obstacle in env.obstacles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (obstacle.rect.centerx, obstacle.rect.centery)
            shape = pymunk.Poly.create_box(body, (obstacle.rect.width, obstacle.rect.height))
            shape.filter = pymunk.ShapeFilter(group=1)
            new_space.add(body, shape)
        return new_space, env
    except Exception as e:
        print(f"Error loading map {map_index}: {e}")
        return None, None


def get_full_state(sonar_data, submarine, map_idx, env_width, batteries):
    normalized_battery = submarine.battery / 600.0
    norm_vx = (submarine.vel_x + 10.0) / 20.0
    norm_vy = (submarine.vel_y + 10.0) / 20.0

    is_straight = 1.0 if map_idx in [0] else 0.0
    is_narrow = 1.0 if map_idx in [1, 2] else 0.0
    is_battery = 1.0 if map_idx in [3, 4] else 0.0
    is_obstacle = 1.0 if map_idx in [5, 6] else 0.0

    map_encoding = [0.0] * 20
    map_encoding[0], map_encoding[1] = is_straight, is_narrow
    map_encoding[2], map_encoding[3] = is_battery, is_obstacle
    map_encoding[-1] = submarine.true_x / env_width

    bat_dx, bat_dy = 0.0, 0.0
    if batteries and len(batteries) > 0:
        closest_dist = float('inf')
        sub_x, sub_y = submarine.rect.centerx, submarine.rect.centery
        for bat in batteries:
            dx = bat.rect.centerx - sub_x
            dy = bat.rect.centery - sub_y
            dist = dx * dx + dy * dy
            if dist < closest_dist:
                closest_dist = dist
                bat_dx, bat_dy = dx, dy
        map_encoding[17] = max(-1.0, min(1.0, bat_dx / 1000.0))
        map_encoding[18] = max(-1.0, min(1.0, bat_dy / 1000.0))

    return np.concatenate([sonar_data, [normalized_battery], [norm_vx, norm_vy], map_encoding])


def get_epsilon(episode):
    if episode < 5000:
        return 1.0
    elif episode < 15000:
        return max(0.1, 1.0 * (EPSILON_DECAY ** (episode - 5000)))
    else:
        return max(0.01, 0.1 * (EPSILON_DECAY ** (episode - 15000)))


def train():
    watch_mode = False

    if not LOAD_MODEL:
        for f in glob.glob("models/*.pth"):
            try:
                os.remove(f)
            except:
                pass
        print("Cleared previous models.")

    spritesheet = SpriteSheet("src/cave_environment/tileset.png")
    print("Pre-loading maps...")
    preloaded_maps = [load_level(i, spritesheet) for i in range(len(MAP_FILES))]

    agent = DoubleDQNAgent(input_shape=39, num_actions=5)
    total_steps = 0

    # --- STATISTICS ---
    map_stats = {i: {'goals': 0, 'attempts': 0, 'total_reward': 0} for i in range(len(MAP_FILES))}

    battery_stats = {
        i: {'picked_up': 0, 'picked_success': 0, 'picked_fail': 0, 'ignored_fail': 0, 'ignored_success': 0}
        for i in range(len(MAP_FILES))
    }
    obstacle_stats = {
        i: {'avoided_won': 0, 'avoided_died': 0, 'hit_died': 0, 'hit_won': 0}
        for i in range(len(MAP_FILES))
    }
    clean_stats = {
        i: {'clean_win': 0, 'dirty_win': 0, 'clean_fail': 0, 'dirty_fail': 0}
        for i in range(len(MAP_FILES))
    }

    start_episode = 0
    if LOAD_MODEL:
        try:
            list_of_files = glob.glob('models/*_ep*.pth')
            latest_file = max(list_of_files,
                              key=os.path.getctime) if list_of_files else "models/ddqn_submarine_final.pth"
            agent.load(latest_file)
            print(f"Loaded: {latest_file}")
            try:
                start_episode = int(latest_file.split("ep")[-1].split(".")[0])
            except:
                pass
        except:
            print("Starting fresh.")

    print(f"Starting Training: 50,000 Episodes (Strict 13-Rule Set)")
    print(f"Printing updates every {SAVE_INTERVAL} episodes.")
    print("Press TAB to toggle 'Watch Mode'.")

    for episode in range(start_episode, NUM_EPISODES):
        epsilon = get_epsilon(episode)
        current_batch = min(4, episode // 10000)
        W = CURRICULUM[current_batch]

        if episode % 10000 == 0 and episode > 0:
            print(f"\n--- BATCH {current_batch + 1}/5 (Rules Verified Constant) ---")

        map_idx = random.randint(0, len(MAP_FILES) - 1)
        map_stats[map_idx]['attempts'] += 1

        space, cave_env = preloaded_maps[map_idx]
        cave_env.batteries.empty()
        cave_env.obstacles.empty()
        wall_rects = [tile.rect for tile in cave_env.environment_tiles]

        with open(MAP_FILES[map_idx], 'r') as f:
            for y, line in enumerate(f.readlines()):
                for x, tile in enumerate(line.strip().split(',')):
                    if tile == '20':
                        from src.entities.items import Battery
                        cave_env.batteries.add(Battery(x * 16, y * 16))
                    elif tile == '21':
                        from src.entities.items import Obstacle
                        cave_env.obstacles.add(Obstacle(x * 16, y * 16))

        total_batteries_in_level = len(cave_env.batteries)
        batteries_collected = 0

        # --- PER-EPISODE FLAGS ---
        hit_obstacle_this_run = False
        hit_wall_this_run = False
        current_run_picked_battery = False
        # -------------------------

        # --- ROBUST SPAWN LOGIC ---
        spawn_collision_rects = wall_rects + [o.rect for o in cave_env.obstacles]
        search_start_x = 100
        start_x, start_y = 100, 300
        found_start = False

        search_zones = list(range(search_start_x, search_start_x + 200, 20)) + \
                       list(range(search_start_x, max(50, search_start_x - 200), -20)) + \
                       list(range(100, 500, 20))

        for x in search_zones:
            if x >= cave_env.environment_width - 50: continue
            valid_ys = []
            for y in range(50, cave_env.environment_height - 50, 20):
                check_rect = pygame.Rect(x - 40, y - 40, 80, 80)
                if check_rect.collidelist(spawn_collision_rects) == -1:
                    valid_ys.append(y)
            if len(valid_ys) > 0:
                start_x, start_y = x, random.choice(valid_ys)
                found_start = True
                break

        if not found_start:
            print(f"WARNING: No safe spawn Map {map_idx}. Forcing 100,300")
            start_x, start_y = 100, 300

        for body in list(space.bodies):
            if body.body_type != pymunk.Body.STATIC:
                space.remove(body)
                for s in body.shapes: space.remove(s)
        if not space: continue

        submarine = Submarine(start_x, start_y)
        submarine.battery = 300 if map_idx in [3, 4] else 600

        # # --- KICKSTART ---
        # submarine.vel_x = 2.0
        MAX_SPEED = 10.0

        sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
        space.add(sonar_body)
        sonar = Sonar(space, sonar_body)

        state = get_full_state(sonar.get_observation(), submarine, map_idx, cave_env.environment_width,
                               cave_env.batteries)
        total_reward = 0
        done = False
        prev_x = submarine.true_x
        prev_y = submarine.true_y
        stagnation_start = submarine.true_x
        stagnation_timer = 0
        success = False  # Track if goal was reached

        for step in range(MAX_STEPS):
            for event in pygame.event.get():
                if event.type == pygame.QUIT: pygame.quit(); return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                    watch_mode = not watch_mode

            action = agent.select_action(state, epsilon)
            reward = 0.0
            prev_x = submarine.true_x
            prev_y = submarine.true_y

            if action == 0:
                submarine.move_up()
            elif action == 1:
                submarine.move_down()
            elif action == 2:
                submarine.move_left()
            elif action == 3:
                submarine.move_right()
            elif action == 4:
                reward += W['glide_reward']

            # --- CLAMP VELOCITY ---
            submarine.vel_x = max(-MAX_SPEED, min(MAX_SPEED, submarine.vel_x))
            submarine.vel_y = max(-MAX_SPEED, min(MAX_SPEED, submarine.vel_y))

            submarine.update()
            sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)

            dist_moved = submarine.true_x - prev_x
            raw_drive = dist_moved * W['forward_drive_mult']
            reward += max(-1.0, min(2.0, raw_drive))

            # --- ROBUST COLLISION DETECTION ---
            hit_wall = False
            if submarine.rect.collidelist(wall_rects) != -1:
                hit_wall = True

            if hit_wall:
                reward += W['wall_penalty']
                submarine.battery -= 10
                submarine.true_x = prev_x
                submarine.true_y = prev_y
                submarine.vel_x *= -0.5
                submarine.vel_y *= -0.5
                submarine.rect.x = int(submarine.true_x)
                submarine.rect.y = int(submarine.true_y)
                sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
                hit_wall_this_run = True  # Track stat

            obs_hits = pygame.sprite.spritecollide(submarine, cave_env.obstacles, True)
            for hit in obs_hits:
                submarine.battery -= 50
                reward += W['obstacle_hit']
                hit_obstacle_this_run = True  # Track stat

            hits = pygame.sprite.spritecollide(submarine, cave_env.batteries, True)
            for hit in hits:
                submarine.battery += 300
                reward += W['battery_reward']
                batteries_collected += 1
                current_run_picked_battery = True  # Track stat

            if submarine.rect.right >= cave_env.environment_width - 10:
                reward += W['goal_reward']
                reward += (submarine.battery * 0.1)
                if batteries_collected >= total_batteries_in_level and total_batteries_in_level > 0:
                    reward += W['all_batteries_bonus']
                done = True
                success = True  # Victory!
                map_stats[map_idx]['goals'] += 1

            if submarine.battery <= 0:
                reward += W['death_penalty']
                done = True

            stagnation_timer += 1
            if stagnation_timer >= 300:
                if abs(submarine.true_x - stagnation_start) < 50:
                    reward += W['stagnation_pen']
                    done = True
                stagnation_timer = 0
                stagnation_start = submarine.true_x

            next_state = get_full_state(sonar.get_observation(), submarine, map_idx, cave_env.environment_width,
                                        cave_env.batteries)
            agent.memory.push(state, action, reward, next_state, done)

            if step % 4 == 0: agent.train_step(BATCH_SIZE)
            total_steps += 1
            if total_steps % TARGET_UPDATE == 0: agent.update_target_network()

            total_reward += reward
            state = next_state

            if watch_mode:
                canvas = pygame.Surface((cave_env.environment_width, cave_env.environment_height))
                canvas.fill((0, 128, 255))
                cave_env.draw(canvas)
                submarine.draw(canvas)
                scale = min(1200 / cave_env.environment_width, 800 / cave_env.environment_height)
                new_size = (int(cave_env.environment_width * scale), int(cave_env.environment_height * scale))
                scaled = pygame.transform.smoothscale(canvas, new_size)
                screen.fill((0, 0, 0))
                screen.blit(scaled, ((1200 - new_size[0]) // 2, (800 - new_size[1]) // 2))
                info = f"Ep: {episode} | Reward: {total_reward:.1f} | Eps: {epsilon:.3f} | TAB to hide"
                screen.blit(font.render(info, True, (255, 255, 255)), (10, 10))
                pygame.display.flip()
                clock.tick(60)

            if done: break

        map_stats[map_idx]['total_reward'] += total_reward

        # 1. Battery Stats
        if current_run_picked_battery:
            battery_stats[map_idx]['picked_up'] += 1
            if success:
                battery_stats[map_idx]['picked_success'] += 1
            else:
                battery_stats[map_idx]['picked_fail'] += 1
        else:
            if success:
                battery_stats[map_idx]['ignored_success'] += 1
            else:
                battery_stats[map_idx]['ignored_fail'] += 1

        # 2. Obstacle Stats
        if hit_obstacle_this_run:
            if success:
                obstacle_stats[map_idx]['hit_won'] += 1
            else:
                obstacle_stats[map_idx]['hit_died'] += 1
        else:
            if success:
                obstacle_stats[map_idx]['avoided_won'] += 1
            else:
                obstacle_stats[map_idx]['avoided_died'] += 1

        # 3. Clean Run Stats (No walls, no obstacles)
        is_clean = (not hit_wall_this_run) and (not hit_obstacle_this_run)
        if is_clean:
            if success:
                clean_stats[map_idx]['clean_win'] += 1
            else:
                clean_stats[map_idx]['clean_fail'] += 1
        else:
            if success:
                clean_stats[map_idx]['dirty_win'] += 1
            else:
                clean_stats[map_idx]['dirty_fail'] += 1

        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/ddqn_submarine_ep{episode}.pth")
            print(f"Ep {episode} | Map {map_idx} | Reward: {total_reward:.1f} | Eps: {epsilon:.3f}")

    # --- FINAL STATISTICS REPORTS ---
    print("\n" + "=" * 80)
    print("TRAINING COMPLETE - FINAL STATISTICS")
    print("=" * 80)
    print(f"{'Map File':<30} | {'Goals':<6} | {'Attempts':<8} | {'Success Rate':<12} | {'Avg Reward':<10}")
    print("-" * 80)

    for i, filename in enumerate(MAP_FILES):
        stats = map_stats[i]
        attempts = stats['attempts']
        goals = stats['goals']
        total_reward = stats['total_reward']

        if attempts > 0:
            success_rate = (goals / attempts) * 100
            avg_reward = total_reward / attempts
        else:
            success_rate = 0.0
            avg_reward = 0.0

        display_name = filename.split('/')[-1]
        print(f"{display_name:<30} | {goals:<6} | {attempts:<8} | {success_rate:<11.1f}% | {avg_reward:<10.1f}")

    # --- BATTERY STATS TABLE ---
    print("\n" + "=" * 90)
    print("BATTERY STATS")
    print("=" * 90)
    print(
        f"{'Map File':<30} | {'Picked(Up)':<10} | {'Picked(Win)':<11} | {'Picked(Die)':<11} | {'Ignored(Die)':<12} | {'Ignored(Win)':<12}")
    print("-" * 90)
    for i, filename in enumerate(MAP_FILES):
        bs = battery_stats[i]
        display_name = filename.split('/')[-1]
        print(
            f"{display_name:<30} | {bs['picked_up']:<10} | {bs['picked_success']:<11} | {bs['picked_fail']:<11} | {bs['ignored_fail']:<12} | {bs['ignored_success']:<12}")

    # --- OBSTACLE STATS TABLE ---
    print("\n" + "=" * 80)
    print("OBSTACLE STATS")
    print("=" * 80)
    print(f"{'Map File':<30} | {'Avoid(Win)':<11} | {'Avoid(Die)':<11} | {'Hit(Die)':<10} | {'Hit(Win)':<10}")
    print("-" * 80)
    for i, filename in enumerate(MAP_FILES):
        os_stat = obstacle_stats[i]
        display_name = filename.split('/')[-1]
        print(
            f"{display_name:<30} | {os_stat['avoided_won']:<11} | {os_stat['avoided_died']:<11} | {os_stat['hit_died']:<10} | {os_stat['hit_won']:<10}")

    # --- CLEAN RUN STATS TABLE ---
    print("\n" + "=" * 80)
    print("CLEAN RUN STATS (No Wall/Obstacle Hits)")
    print("=" * 80)
    print(f"{'Map File':<30} | {'Clean Win':<10} | {'Dirty Win':<10} | {'Clean Fail':<10} | {'Dirty Fail':<10}")
    print("-" * 80)
    for i, filename in enumerate(MAP_FILES):
        cs = clean_stats[i]
        display_name = filename.split('/')[-1]
        print(
            f"{display_name:<30} | {cs['clean_win']:<10} | {cs['dirty_win']:<10} | {cs['clean_fail']:<10} | {cs['dirty_fail']:<10}")

    print("=" * 80)
    print("Loss saved.")

    agent.save("models/ddqn_submarine_final.pth")
    pygame.quit()


if __name__ == "__main__":
    train()