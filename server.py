import random
from ebsockets import connections
ebs_event = connections.ebsocket_event

from scripts import game_logic

import time


id_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'


def new_id(length=24):
    return ''.join([random.choice(id_chars) for _ in range(length)])


server = connections.ebsocket_server(7982)
system = connections.ebsocket_system(server)

system.timeout = 0.25

print(f"Server hosting on : {server.address[0]}:{server.address[1]}")


class connected_player(object):
    def __init__(self,
                 system: connections.ebsocket_system,
                 connection: connections.socket.socket,
                 address: str):

        self.system = system
        self.connection = connection
        self.address = address

        self.state = 'in_menus'
        self.game_id = None
        self.uno_player = None

    def __repr__(self):
        return f'<connected_player({self.address},{self.username})>'


connected_players = {}

running_games = {}
waiting_games = []

def find_player_by_uno_player(uno_player):
    try:
        return [p for p in connected_players.values() if p.uno_player == uno_player][0]
    except:
        return None


game_size = 5
game_size_min = 1


while True:
    ct = time.time()

    new_clients, new_events, disconnected_clients = system.pump()

    for new_client in new_clients:
        connection, address = new_client
        print(f"New connection: {connection}:{address}")
        connection.setblocking(0)
        player = connected_player(system, connection, address)
        connected_players[connection] = player
        system.send_event_to(connection, ebs_event('connected', state=True))
    

    
    waiting_players = [p for p in connected_players.values() if p.state == 'waiting']

    started_games = []
    for game in waiting_games:
        if game.creation_time+5 < ct:
            # 5 second window to join a currently waiting game
            print('game started!')

            game_id = game.game_id
            running_games[game_id] = game

            game.start_game(len(game.waiting_players), 7)

            all_ftcs = [p.ftc for p in game.waiting_players]

            for i,player in enumerate(game.waiting_players):
                player.state = 'in_game'
                player.game_id = game_id
                player.uno_player = game.players[i]

                system.send_event_to(player.connection,
                ebs_event('join_game'))
                
                system.send_event_to(player.connection,
                ebs_event('update_hand',
                cards=player.uno_player.hand))
                
                system.send_event_to(player.connection,
                ebs_event('set_upcard',
                card=game.upfacing_card))
                
                system.send_event_to(player.connection,
                ebs_event('set_player_sprites',
                own_index=i, all_ftcs=all_ftcs))
                
                if i == game.players_turn:
                    system.send_event_to(player.connection,
                    ebs_event('your_turn', value=True))
            
            started_games.append(game)
    
    for game in started_games:
        waiting_games.remove(game)

    for game in [g for g in waiting_games if len(g.waiting_players)<game_size_min]:
        # prevent games with less than 2 players from starting
        game.creation_time = ct
    
    if len(waiting_players) > 0:
        # put at least two players in a game together, just for testing
        # figure out a better way to arrange games later

        waiting_players = [p for p in connected_players.values() if p.state == 'waiting']

        for new_player in waiting_players:
            print('new player found waiting')

            joinable_games = [g for g in waiting_games if len(g.waiting_players)<game_size]

            if len(joinable_games) == 0:
                print('creating new game for players')
                game_id = new_id()
                players = [new_player,]
                new_game = game_logic.UnoGame()
                new_game.creation_time = ct
                new_game.game_id = game_id
                new_game.waiting_players = players

                for player in players:
                    player.state = 'joining_game'

                waiting_games.append(new_game)

            else:
                print('putting the player into existing waiting game')
                join_game = joinable_games[0]
                join_game.waiting_players.append(new_player)
                new_player.state = 'joining_game'
                game_id = join_game.game_id

            



    for event in new_events:
        print(f"New event: {event}")
        from_connection = event.from_connection
        player = connected_players[from_connection]

        game_id = player.game_id
        current_game = running_games.get(game_id, None)

        if event.event == 'join':
            print('player join')
            player.state = 'waiting'
            player.ftc = event.player_ftc

        if current_game is not None:
            player_index = current_game.players.index(player.uno_player)

            game_state_changed = False

            if event.event == 'play':
                # a player playing a card or picking up a card
                print('player try play :', event.turn)
                if current_game.players_turn == player_index:
                    # it is this player's turn
                    print('it is player\'s turn')
                    print(current_game.players_turn, '<- before turn')
                    valid_move = current_game.take_turn(player_index, event.turn)
                    print(current_game.players_turn, '<- after turn')
                    if valid_move:
                        print('move is valid')
                        game_state_changed = True
            
            if game_state_changed:
                players = []
                for uno_player in current_game.players:
                    found_player = find_player_by_uno_player(uno_player)
                    players.append(found_player)
                
                system.send_event_to(player.connection,
                ebs_event('your_turn', value=False))

                for i,other_player in enumerate(players):
                    system.send_event_to(other_player.connection,
                    ebs_event('set_upcard',
                    card=current_game.upfacing_card))
                    
                    system.send_event_to(other_player.connection,
                    ebs_event('set_stacked',
                    stacked=current_game.stacked_plus))
                    
                    system.send_event_to(other_player.connection,
                    ebs_event('set_player_turn',
                    turn=current_game.players_turn))

                system.send_event_to(players[current_game.players_turn].connection,
                ebs_event('your_turn', value=True))
            
                system.send_event_to(from_connection,
                ebs_event('update_hand',
                cards=player.uno_player.hand))



    for client in disconnected_clients:
        connection, address = client
        print(f"Client disconnected {address[0]}:{address[1]}")
        player = connected_players.pop(connection)
        if player.game_id is not None:
            current_game = running_games.get(player.game_id, None)
            if current_game is not None:
                
                other_players = [p for p in connected_players.values() if p.game_id == player.game_id]

                if len(other_players) == 0:
                    running_games.pop(player.game_id)
                    print('closed game due to abandonment')

                else:
                    uno_player = player.uno_player
                    print(f'player left : {uno_player}')

                    player_index = current_game.players.index(player.uno_player)
                    print(f'player index : {player_index}')

                    print(f'before pop : {current_game.players}')
                    current_game.players.pop(player_index)
                    print(f'after pop : {current_game.players}')

                    if current_game.turn_direction > 0:
                        if current_game.players_turn <= player_index:
                            current_game.players_turn -= current_game.turn_direction
                    elif current_game.turn_direction < 0:
                        if current_game.players_turn >= player_index:
                            current_game.players_turn -= current_game.turn_direction
                    current_game.players_turn %= len(current_game.players)

                    print('finding players...')
                    players = []
                    for uno_player in [p for p in current_game.players if p != player.uno_player]:
                        print(f'  try find player : {uno_player}')
                        found_player = find_player_by_uno_player(uno_player)
                        if found_player is not None:
                            players.append(found_player)
                        else:
                            print(f'  could not get player')
                    
                    all_ftcs = [p.ftc for p in players]
                    for i,other_player in enumerate(players):
                        system.send_event_to(other_player.connection,
                        ebs_event('your_turn', value=False))

                        system.send_event_to(other_player.connection,
                        ebs_event('set_player_sprites',
                        own_index=i, all_ftcs=all_ftcs))
                    
                        system.send_event_to(other_player.connection,
                        ebs_event('set_player_turn',
                        turn=current_game.players_turn))
                    
                    system.send_event_to(players[current_game.players_turn].connection,
                    ebs_event('your_turn', value=True))

'''
check for game winner when play is made or when player leaves game
'''