import dataset
db = dataset.connect('sqlite:///bot_database.db')
def save_inviter(user_id: int, username: str, ref_link: str):
    update_bet_pairs = db['bet_pairs']
    data = {
        'inviter_id': user_id,
        'inviter_username': username,
        'ref_link': ref_link
    }
    update_bet_pairs.upsert(data, ['id'])
def save_invitee(user_id: int, username: str, ref_link: str):
    update_bet_pairs = db['bet_pairs']
    data = {
        'invitee_id': user_id,
        'invitee_username': username,
        'ref_link': ref_link
    }
    update_bet_pairs.update(data, ['ref_link'])

def save_function(info: dict, table_name: str, primary_column: str):
    table_name = db[table_name]
    table_name.upsert(info, [primary_column])
    
def update_function(info: dict, table_name: str, primary_column: str):
    table_name = db[table_name]
    table_name.upsert(info, [primary_column])

def retrieve_value(key_column: str, key_value: str, table_name: str, return_key: str):
    # Connect to the database and select the table
    table = db[table_name]
    
    # Query the database for the record where key_column matches key_value
    record = table.find_one(**{key_column: key_value})
    
    # Return the value of return_key if the record exists, otherwise None
    return record[return_key] if record else None

