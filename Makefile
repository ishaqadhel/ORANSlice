.PHONY: install-docker

install-docker:
	@echo "Installing Docker..."
	sudo apt-get update
	sudo apt-get install -y ca-certificates curl
	sudo install -m 0755 -d /etc/apt/keyrings
	sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	sudo chmod a+r /etc/apt/keyrings/docker.asc
	@echo "Types: deb" | sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null
	@echo "URIs: https://download.docker.com/linux/ubuntu" | sudo tee -a /etc/apt/sources.list.d/docker.sources > /dev/null
	@echo "Suites: $$(. /etc/os-release && echo "$${UBUNTU_CODENAME:-$$VERSION_CODENAME}")" | sudo tee -a /etc/apt/sources.list.d/docker.sources > /dev/null
	@echo "Components: stable" | sudo tee -a /etc/apt/sources.list.d/docker.sources > /dev/null
	@echo "Architectures: $$(dpkg --print-architecture)" | sudo tee -a /etc/apt/sources.list.d/docker.sources > /dev/null
	@echo "Signed-By: /etc/apt/keyrings/docker.asc" | sudo tee -a /etc/apt/sources.list.d/docker.sources > /dev/null
	sudo apt-get update
	sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
	@echo "Docker installed successfully!"