import torch
import torch.nn as nn

from torch.autograd import Variable
from torch import cat

from model import UNet	

########################################################################
# The output of torchvision datasets are PILImage images of range [0, 1].
# We transform them to Tensors.
tensor_transform = transforms.ToTensor()

testset = torchvision.datasets.CIFAR10(root='./data', train=False,
                                       download=True, transform=tensor_transform)

#########################################################################
# Transform the images to CieLAB color space by the use of OpenCV library.
rgb_images = []
numpy_lab_images = []
for image, label in testset:
    rgb_images.append(image)

for rgb_image in rgb_images:
    numpy_rgb_image = np.transpose(rgb_image.numpy(), (1, 2, 0))
    numpy_lab_image = cv2.cvtColor(numpy_rgb_image, cv2.COLOR_RGB2LAB)
    numpy_lab_images.append(numpy_lab_image)

######################################################################
# Transform the numpy lab images to images of range [0, 1] and further
# convert them to tensors.
lab_images = []
for numpy_lab_image in numpy_lab_images:
    numpy_lab_image[:, :, 0] *= 255 / 100
    numpy_lab_image[:, :, 1] += 128
    numpy_lab_image[:, :, 2] += 128
    numpy_lab_image /= 255
    torch_lab_image = torch.from_numpy(np.transpose(numpy_lab_image, (2, 0, 1)))
    lab_images.append(torch_lab_image)

#######################################################################
# Make a custom CieLAB dataset and a data loader that iterates over the
# custom dataset without shuffling and a batch size of 128.
class CieLABDataset(torch.utils.data.Dataset):
    """CieLab dataset."""    
    def __len__(self):
        return len(lab_images)

    def __getitem__(self, index):
        img = lab_images[index]
        return img

cielab_dataset = CieLABDataset()
cielab_loader = torch.utils.data.DataLoader(cielab_dataset, batch_size=128,
                  shuffle=False, num_workers=2)

#####################################################
# Initialise the generatorwith the UNet architecture.
generator = UNet(True)

##################################################################
# Utilize GPU for performing all the calculations performed in the
# forward passes. Thus allocate all the generator variables on the 
# default GPU device.
generator.cuda()

###################################################################
# Create loss criterion for calculating the L1 image distance loss.
l_criterion = nn.L1Loss()

eval_()

def eval_():
	"""
	Evaluate the test dataset using L1 loss between the source and the generated image.
	"""
	running_loss = 0.0
	num_steps = 0
    for i, data in enumerate(cielab_loader):
    	num_steps = num_steps + 1
        test_images = data
        # split the lab color space images into luminescence and chrominance channels.
        l_images = lab_images[:, 0, :, :]
        c_images = lab_images[:, 1:, :, :]
        # shift the source and target images into the range [-0.5, 0.5].
        mean = torch.Tensor([0.5])
        l_images = l_images - mean.expand_as(l_images)
        l_images = 2 * l_images
        
        c_images = c_images - mean.expand_as(c_images)
        c_images = 2 * c_images
        # allocate the images on the default gpu device.
        batch_size = l_images.shape[0]
        l_images = Variable(l_images.cuda())
        c_images = Variable(c_images.cuda())
        # fake images are generated by passing them through the generator.
        fake_images = generator(l_images)
        
        # Calculate the image distance loss pixelwise between the images.
        loss = l_criterion(fake_images, c_images)
		running_loss += loss
    
    print('Mean Absolute Error(MAE): ', running_loss / num_steps)
