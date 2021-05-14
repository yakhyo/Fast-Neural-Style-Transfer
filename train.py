import os
import time

import tqdm
import yaml
import numpy as np

import torch
import torchvision

from utils import util
from nets.nn import TransformerNet, VGG16


def train(config, device):
    # Train config
    config = config['TRAIN']

    style_name = config['style_image'].split("/")[-1].split(".")[0]
    os.makedirs(f"{config['save_model_dir']}", exist_ok=True)

    np.random.seed(config['seed'])
    torch.manual_seed(config['seed'])

    # Dataset and dataloader
    train_dataset = torchvision.datasets.ImageFolder(config['dataset'], util.train_transform(config['image_size']))
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=config['batch_size'])

    # Neural Network
    transformer = TransformerNet().to(device)
    vgg = VGG16(requires_grad=False).to(device)

    # Optimizer and loss
    optimizer = torch.optim.Adam(transformer.parameters(), config['lr'])
    mse_loss = torch.nn.MSELoss()

    # Load style image
    style = util.load_image(config['style_image'], size=config['style_size'])
    style = util.transform(style)
    style = style.repeat(config['batch_size'], 1, 1, 1).to(device)

    # Extract features
    features_style = vgg(util.normalize_batch(style))
    gram_style = [util.gram_matrix(y) for y in features_style]

    # Train
    log = open('logs.txt', 'a')
    for epoch in range(config['num_epochs']):
        transformer.train()
        metrics = {"content": [], "style": [], "total": []}
        count = 0

        print(('\n' + '%10s' * 2) % ('Epoch', 'GPU'))
        progress_bar = tqdm.tqdm(enumerate(train_loader), total=len(train_loader))
        for batch_id, (x, _) in progress_bar:
            n_batch = len(x)
            count += n_batch
            optimizer.zero_grad()

            x = x.to(device)
            y = transformer(x)

            y = util.normalize_batch(y)
            x = util.normalize_batch(x)

            features_y = vgg(y)
            features_x = vgg(x)

            content_loss = config['content_weight'] * mse_loss(features_y.relu2_2, features_x.relu2_2)

            style_loss = 0.
            for ft_y, gm_s in zip(features_y, gram_style):
                gm_y = util.gram_matrix(ft_y)
                style_loss += mse_loss(gm_y, gm_s[:n_batch, :, :])
            style_loss *= config['style_weight']

            total_loss = content_loss + style_loss
            total_loss.backward()
            optimizer.step()

            metrics['content'] += [content_loss.item()]
            metrics['style'] += [style_loss.item()]
            metrics['total'] += [total_loss.item()]

            if (batch_id + 1) % config['log_interval'] == 0:
                info = "{}\tEpoch {}:\t[{}/{}]\tContent: {:.2f}\tStyle: {:.2f}\tTotal: {:.2f}\n".format(
                    time.ctime(), epoch + 1, count, len(train_dataset),
                    np.mean(metrics['content']),
                    np.mean(metrics['style']),
                    np.mean(metrics['total'])
                )
                log.write(info)

            memory = '%.3gG' % (torch.cuda.memory_reserved() / 1E9 if torch.cuda.is_available() else 0)
            s = (('%10s' + '%10s') % (epoch + 1, memory))
            progress_bar.set_description(s)

    # save model
    transformer.eval().cpu()
    model_name = f'{style_name}.pth'
    save_model_path = os.path.join(config['save_model_dir'], model_name)
    torch.save(transformer.state_dict(), save_model_path)
    log.close()
    print("\nTrain finished ", save_model_path)


if __name__ == "__main__":
    # Default config
    with open(r'utils/config.yaml') as file:
        config = yaml.load(file, Loader=yaml.FullLoader)

    # Configure device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    train(config=config, device=device)
