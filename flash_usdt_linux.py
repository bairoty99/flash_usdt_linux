import os
import json
import time
from web3 import Web3
from web3.exceptions import ContractLogicError
from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.exceptions import TransactionError
from dotenv import load_dotenv

# Load environment variables (optional, fallback to defaults)
load_dotenv()

# Config (edit these or use .env)
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
TRON_RPC_URL = os.getenv("TRON_RPC_URL", "https://api.trongrid.io")
BSC_PRIVATE_KEY = os.getenv("BSC_PRIVATE_KEY", "your_bsc_private_key_here")
TRON_PRIVATE_KEY = os.getenv("TRON_PRIVATE_KEY", "your_tron_private_key_here")
BSC_CONTRACT_ADDRESS = os.getenv("BSC_CONTRACT_ADDRESS")
TRON_CONTRACT_ADDRESS = os.getenv("TRON_CONTRACT_ADDRESS")

# Smart Contract Source (embedded)
CONTRACT_SOURCE = """
pragma solidity ^0.8.0;

contract FlashUSDT {
    string public name = "Flash USDT";
    string public symbol = "FUSDT";
    uint8 public decimals = 6;
    uint256 public totalSupply;
    uint256 public expirationTime;
    address public owner;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => uint256) public licensedLimits;

    event Transfer(address indexed from, address indexed to, uint256 value);

    constructor(uint256 _initialSupply, uint256 _expiration) {
        totalSupply = _initialSupply * 10 ** decimals;
        owner = msg.sender;
        balanceOf[msg.sender] = totalSupply;
        expirationTime = block.timestamp + _expiration;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }

    function transfer(address _to, uint256 _value) public returns (bool) {
        require(block.timestamp < expirationTime, "Tokens expired");
        require(balanceOf[msg.sender] >= _value, "Insufficient balance");
        require(licensedLimits[msg.sender] >= _value, "Exceeds license limit");
        balanceOf[msg.sender] -= _value;
        balanceOf[_to] += _value;
        licensedLimits[msg.sender] -= _value;
        emit Transfer(msg.sender, _to, _value);
        return true;
    }

    function burnExpired() public onlyOwner {
        require(block.timestamp >= expirationTime, "Tokens not yet expired");
        balanceOf[owner] = 0;
        totalSupply = 0;
    }

    function setLicense(address _user, uint256 _limit) public onlyOwner {
        licensedLimits[_user] = _limit;
    }
}
"""

# Initialize Web3 (BSC)
bsc_w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL))
bsc_account = bsc_w3.eth.account.from_key(BSC_PRIVATE_KEY)

# Initialize Tron
tron = Tron(full_node=TRON_RPC_URL, private_key=TRON_PRIVATE_KEY)
tron_private_key = PrivateKey(bytes.fromhex(TRON_PRIVATE_KEY))

# Deploy contract if not already deployed
def deploy_contract(network):
    if network == "bsc":
        if not BSC_CONTRACT_ADDRESS:
            print("Deploying FlashUSDT contract on BSC mainnet...")
            compiled = bsc_w3.eth.compile.solidity(CONTRACT_SOURCE)
            contract_interface = compiled['<stdin>:FlashUSDT']
            contract = bsc_w3.eth.contract(abi=contract_interface['abi'], bytecode=contract_interface['bin'])
            tx = contract.constructor(1000000, 86400).build_transaction({
                "from": bsc_account.address,
                "nonce": bsc_w3.eth.get_transaction_count(bsc_account.address),
                "gas": 2000000,
                "gasPrice": bsc_w3.eth.gas_price
            })
            signed_tx = bsc_w3.eth.account.sign_transaction(tx, BSC_PRIVATE_KEY)
            tx_hash = bsc_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = bsc_w3.eth.wait_for_transaction_receipt(tx_hash)
            with open("contractABI.json", "w") as f:
                json.dump(contract_interface['abi'], f)
            print(f"BSC Contract deployed at: {receipt.contractAddress}")
            return receipt.contractAddress, contract_interface['abi']
        else:
            with open("contractABI.json", "r") as f:
                return BSC_CONTRACT_ADDRESS, json.load(f)

    elif network == "tron":
        if not TRON_CONTRACT_ADDRESS:
            print("Deploying FlashUSDT contract on Tron mainnet...")
            # Tron deployment simplified (requires manual bytecode prep for now)
            # For simplicity, assume pre-deployed or use TronBox externally
            raise NotImplementedError("Tron deployment requires TronBox or external tool. Please deploy manually and set TRON_CONTRACT_ADDRESS.")
        else:
            with open("contractABI.json", "r") as f:
                return TRON_CONTRACT_ADDRESS, json.load(f)

# Load or deploy contracts
bsc_contract_address, bsc_abi = deploy_contract("bsc")
tron_contract_address, tron_abi = deploy_contract("tron")  # Note: Tron deployment needs external step

bsc_contract = bsc_w3.eth.contract(address=bsc_contract_address, abi=bsc_abi)
tron_contract = tron.get_contract(tron_contract_address)

# License system
def set_license(wallet, limit, network):
    if network == "bsc":
        tx = bsc_contract.functions.setLicense(wallet, int(limit * 10**6)).build_transaction({
            "from": bsc_account.address,
            "nonce": bsc_w3.eth.get_transaction_count(bsc_account.address),
            "gas": 200000,
            "gasPrice": bsc_w3.eth.gas_price
        })
        signed_tx = bsc_w3.eth.account.sign_transaction(tx, BSC_PRIVATE_KEY)
        tx_hash = bsc_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"BSC License Tx Hash: {bsc_w3.to_hex(tx_hash)}")
    elif network == "tron":
        tx = tron_contract.functions.setLicense(wallet, int(limit * 10**6)).build_transaction()
        signed_tx = tron_private_key.sign(tx)
        tx_hash = tron.trx.send_raw_transaction(signed_tx)
        print(f"Tron License Tx Hash: {tx_hash}")

# Generate Flash USDT
def generate_flash_usdt(wallet, amount, network):
    amount_with_decimals = int(amount * 10**6)
    
    if network == "bsc":
        try:
            expiry = bsc_contract.functions.expirationTime().call()
            if int(time.time()) >= expiry:
                print("Tokens expired. Burning...")
                burn_tx = bsc_contract.functions.burnExpired().build_transaction({
                    "from": bsc_account.address,
                    "nonce": bsc_w3.eth.get_transaction_count(bsc_account.address),
                    "gas": 200000,
                    "gasPrice": bsc_w3.eth.gas_price
                })
                signed_burn_tx = bsc_w3.eth.account.sign_transaction(burn_tx, BSC_PRIVATE_KEY)
                bsc_w3.eth.send_raw_transaction(signed_burn_tx.rawTransaction)
                time.sleep(5)

            tx = bsc_contract.functions.transfer(wallet, amount_with_decimals).build_transaction({
                "from": bsc_account.address,
                "nonce": bsc_w3.eth.get_transaction_count(bsc_account.address),
                "gas": 200000,
                "gasPrice": bsc_w3.eth.gas_price
            })
            signed_tx = bsc_w3.eth.account.sign_transaction(tx, BSC_PRIVATE_KEY)
            tx_hash = bsc_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            print(f"BSC Tx Hash: {bsc_w3.to_hex(tx_hash)}")
        except ContractLogicError as e:
            print(f"Error: {e}")

    elif network == "tron":
        try:
            expiry = tron_contract.functions.expirationTime().call()
            if int(time.time()) >= expiry:
                print("Tokens expired. Burning...")
                burn_tx = tron_contract.functions.burnExpired().build_transaction()
                signed_burn_tx = tron_private_key.sign(burn_tx)
                tron.trx.send_raw_transaction(signed_burn_tx)
                time.sleep(5)

            tx = tron_contract.functions.transfer(wallet, amount_with_decimals).build_transaction()
            signed_tx = tron_private_key.sign(tx)
            tx_hash = tron.trx.send_raw_transaction(signed_tx)
            print(f"Tron Tx Hash: {tx_hash}")
        except TransactionError as e:
            print(f"Error: {e}")

# CLI Interface
def main():
    print("Flash USDT Tool (Linux - Mainnet)")
    print("---------------------------------")
    
    while True:
        print("\nOptions: 1) Generate Flash USDT  2) Set License  3) Exit")
        choice = input("Choose an option (1-3): ").strip()

        if choice == "1":
            wallet = input("Enter target wallet address: ")
            amount = float(input("Enter amount of Flash USDT: "))
            network = input("Enter network (bsc/tron): ").strip().lower()
            print(f"Generating {amount} Flash USDT to {wallet} on {network}...")
            generate_flash_usdt(wallet, amount, network)

        elif choice == "2":
            wallet = input("Enter wallet address to license: ")
            limit = float(input("Enter max token limit: "))
            network = input("Enter network (bsc/tron): ").strip().lower()
            print(f"Setting license for {wallet} to {limit} on {network}...")
            set_license(wallet, limit, network)

        elif choice == "3":
            print("Exiting...")
            break

        else:
            print("Invalid choice. Try again.")

if __name__ == "__main__":
    # Ensure mainnet connectivity
    if not bsc_w3.is_connected():
        print("Error: Cannot connect to BSC mainnet.")
        exit(1)
    if not tron.is_connected():
        print("Error: Cannot connect to Tron mainnet.")
        exit(1)
    main()
